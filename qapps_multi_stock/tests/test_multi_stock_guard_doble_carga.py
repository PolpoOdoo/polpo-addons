# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Guard contra la SEGUNDA CARGA de la misma venta (doble remito).

Causa raiz: ``_multi_stock_apply`` no era idempotente. El core NO deja
reconfirmar un pedido que ya esta en ``sale`` (``sale.order._can_be_confirmed``
solo admite ``draft``/``sent``), pero SI deja cancelar -> volver a borrador ->
reconfirmar, y ese camino vuelve a pasar por el motor. Al cancelar la venta,
``_multi_stock_cancel_pickings`` cancela solo los documentos PENDIENTES y deja
los VALIDADOS, que ya movieron mercaderia. En la segunda pasada el faltante se
vuelve a medir COMPLETO, porque ``_multi_stock_delivery_moves`` mira solo los
moves de entrega VIVOS y lo ya despachado por el origen no esta entre ellos:
``reservado_local`` quedaba en 0 y se generaba un segundo traslado/drop-ship por
la misma mercaderia.

Por eso los tests que bloquean van TODOS por cancelar -> borrador ->
reconfirmar, y con el documento previo VALIDADO. Un test que llame dos veces
seguidas a ``action_confirm()`` sobre el mismo pedido da verde sin guard: el
``UserError`` que ve es el del core (not in a state requiring confirmation), no
el nuestro. ``test_el_core_no_deja_reconfirmar_un_pedido_en_sale`` deja esa
premisa anclada.

Caso real que lo motivo: tres pedidos con DOS drop-ship validados contra la
misma linea de venta, creados con minutos de diferencia y por usuarios
distintos. Se despacho el doble de lo vendido.

Casos hermanos que NO se bloquean, y por que la foto se saca antes del loop:
- R2 crea DOS pickings (despacho + recepcion) por linea en una sola pasada.
- Dos lineas del MISMO producto en un pedido son dos despachos legitimos
  (``sale_line_id`` es distinct field del merge de ``stock.move``, asi que los
  moves no se fusionan y cada linea genera el suyo).
- Otra venta del mismo cliente y producto es una venta nueva, no una segunda
  carga: el guard esta acotado a ``multi_stock_sale_id = este pedido``.
- Documentos CANCELADOS no bloquean: se cancelaron justamente para rehacer la
  venta.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockGuardDobleCarga(MultiStockCommon):

    def _dropships(self, so):
        return self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])

    def _traslados(self, so):
        return self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "in", [self.type_out.id, self.type_in.id]),
        ])

    def _validar(self, picking):
        picking.sudo().action_assign()
        for ml in picking.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        picking.move_ids.picked = True
        picking.sudo().button_validate()

    def _rehacer(self, so):
        """Camino real de produccion: cancelar el pedido y volverlo a borrador.

        Es la UNICA forma de que ``_multi_stock_apply`` corra dos veces sobre el
        mismo pedido: el core no admite ``action_confirm`` desde ``sale``."""
        so._action_cancel()
        so.action_draft()
        self.assertEqual(so.state, "draft")

    # ------------------------------------------------------------------ #
    #  Premisa: por que los tests van por cancelar -> borrador            #
    # ------------------------------------------------------------------ #
    def test_el_core_no_deja_reconfirmar_un_pedido_en_sale(self):
        """Ancla del resto de la suite. Si esto cambiara (un modulo que pise
        ``_can_be_confirmed``), los tests de bloqueo hay que revisarlos: hoy un
        doble ``action_confirm()`` seguido corta en el core, antes del guard, y
        un test escrito asi da verde aunque el guard no exista."""
        prod = self._producto("Premisa core")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()

        with self.assertRaises(UserError) as ctx:
            so.action_confirm()

        self.assertIn("state requiring confirmation", str(ctx.exception))

    # ------------------------------------------------------------------ #
    #  Casos BLOQUEADOS                                                   #
    # ------------------------------------------------------------------ #
    def test_rehacer_tras_dropship_validado_bloquea(self):
        """Camino real de los pedidos afectados: drop-ship validado, pedido
        cancelado (el validado sobrevive), vuelto a borrador y reconfirmado."""
        prod = self._producto("Doble carga R3")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds = self._dropships(so)
        self._validar(ds)
        self.assertEqual(ds.state, "done")

        self._rehacer(so)
        self.assertEqual(ds.state, "done", "el validado no se cancela")

        with self.assertRaises(UserError):
            so.action_confirm()

        # Rollback de la confirmacion: sigue habiendo un solo documento.
        self.assertEqual(self._dropships(so), ds)

    def test_rehacer_tras_traslado_r2_validado_bloquea(self):
        """Mismo guard por la ruta R2: el despacho del origen ya se valido, no
        se emite otro."""
        prod = self._producto("Doble carga R2")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        previos = self._traslados(so)
        self.assertEqual(len(previos), 2, "R2 genera despacho + recepcion")
        out = previos.filtered(lambda p: p.picking_type_id == self.type_out)
        self._validar(out)
        self.assertEqual(out.state, "done")

        self._rehacer(so)

        with self.assertRaises(UserError):
            so.action_confirm()

        self.assertEqual(self._traslados(so), previos)

    def test_rehacer_bloquea_aunque_el_destino_ya_tenga_stock(self):
        """El corte va ANTES de medir el faltante. Si al rehacer el pedido el
        destino tiene stock propio, el faltante da 0, no se genera documento del
        origen y la linea sale por R1: la entrega nativa despacha de nuevo la
        cantidad completa que el drop-ship validado ya le llevo al cliente.
        Tambien es doble despacho, y un guard puesto despues de medir el
        faltante lo dejaba pasar en silencio."""
        prod = self._producto("Doble carga con stock local")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        self._validar(self._dropships(so))

        self._rehacer(so)
        # Entre medio llego mercaderia al destino: ya no hay faltante.
        self._stock(prod, 50.0, self.wh_dest)

        with self.assertRaises(UserError):
            so.action_confirm()

        self.assertEqual(so.state, "draft")

    def test_mensaje_nombra_el_documento_existente(self):
        """El mensaje tiene que decir CUAL documento ya existe: sin eso el
        usuario no sabe que cancelar o que devolver."""
        prod = self._producto("Doble carga mensaje")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds = self._dropships(so)
        self._validar(ds)
        self._rehacer(so)

        with self.assertRaises(UserError) as ctx:
            so.action_confirm()

        mensaje = str(ctx.exception)
        self.assertIn(ds.name, mensaje)
        self.assertIn(prod.display_name, mensaje)

    def test_guard_sin_excepcion_para_admin(self):
        """Regla del proyecto: las restricciones de negocio no tienen bypass de
        administrador. Rehacer el pedido como superusuario bloquea igual."""
        prod = self._producto("Doble carga admin")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds = self._dropships(so)
        self._validar(ds)
        self._rehacer(so)

        with self.assertRaises(UserError):
            so.sudo().action_confirm()

        self.assertEqual(self._dropships(so), ds)

    # ------------------------------------------------------------------ #
    #  Casos HERMANOS que NO se bloquean                                  #
    # ------------------------------------------------------------------ #
    def test_dos_lineas_mismo_producto_no_se_bloquean(self):
        """Dos lineas del mismo producto en UN pedido: dos despachos legitimos
        en la misma pasada. Es el caso que rompe un guard que busque en vivo
        dentro del loop en lugar de trabajar sobre la foto previa."""
        prod = self._producto("Dos lineas mismo producto")
        self._stock(prod, 100.0, self.wh_src)
        so = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "warehouse_id": self.wh_dest.id,
            "company_id": self.company.id,
            "order_line": [
                (0, 0, {
                    "product_id": prod.id,
                    "product_uom_qty": 10.0,
                    "price_unit": 100.0,
                }),
                (0, 0, {
                    "product_id": prod.id,
                    "product_uom_qty": 4.0,
                    "price_unit": 80.0,
                }),
            ],
        })
        so.order_line.write({"multi_stock_mode": "envio_directo"})

        so.action_confirm()  # no debe levantar UserError

        self.assertEqual(so.state, "sale")
        dropships = self._dropships(so)
        self.assertEqual(len(dropships), 2)
        self.assertEqual(
            sorted(dropships.move_ids.mapped("product_uom_qty")), [4.0, 10.0]
        )

    def test_r2_genera_dos_documentos_en_una_pasada(self):
        """R2 crea despacho + recepcion para UNA linea: el guard no puede
        confundir el segundo documento de la misma pasada con una segunda
        carga."""
        prod = self._producto("R2 dos documentos")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")

        so.action_confirm()  # no debe levantar UserError

        self.assertEqual(so.state, "sale")
        traslados = self._traslados(so)
        self.assertEqual(
            len(traslados.filtered(lambda p: p.picking_type_id == self.type_out)), 1
        )
        self.assertEqual(
            len(traslados.filtered(lambda p: p.picking_type_id == self.type_in)), 1
        )

    def test_otra_venta_mismo_cliente_y_producto_no_se_bloquea(self):
        """Dos ventas distintas al mismo cliente por el mismo producto son dos
        ventas, no una segunda carga. El guard esta acotado al pedido."""
        prod = self._producto("Dos ventas mismo cliente")
        self._stock(prod, 100.0, self.wh_src)
        so1 = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so1.action_confirm()
        self._validar(self._dropships(so1))
        so2 = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")

        so2.action_confirm()  # no debe levantar UserError

        self.assertEqual(so2.state, "sale")
        self.assertEqual(len(self._dropships(so1)), 1)
        self.assertEqual(len(self._dropships(so2)), 1)

    def test_documentos_cancelados_no_bloquean(self):
        """Se cancela el pedido (y con el su drop-ship PENDIENTE) y se rehace:
        tiene que poder generarse el documento nuevo. Es el uso legitimo del
        camino cancelar -> borrador -> reconfirmar."""
        prod = self._producto("Cancelado rehace")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds1 = self._dropships(so)
        self.assertEqual(len(ds1), 1)

        self._rehacer(so)
        self.assertEqual(ds1.state, "cancel", "el pendiente si se cancela")

        so.action_confirm()  # no debe levantar UserError

        self.assertEqual(so.state, "sale")
        vivos = self._dropships(so).filtered(lambda p: p.state != "cancel")
        self.assertEqual(len(vivos), 1)
        self.assertNotEqual(vivos, ds1)

    def test_venta_sin_documentos_previos_se_rehace_sin_bloqueo(self):
        """R1 puro: nunca hubo documento del origen, rehacer el pedido no
        bloquea."""
        prod = self._producto("R1 rehace")
        self._stock(prod, 50.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        so.action_confirm()
        self.assertFalse(self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
        ]))

        self._rehacer(so)
        so.action_confirm()  # no debe levantar UserError

        self.assertEqual(so.state, "sale")
        self.assertFalse(self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
        ]))
