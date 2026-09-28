# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Visibilidad, para el vendedor del DESTINO, de los documentos que el multi
depósito genera en la compañía del ORIGEN (rutas R2 y R3).

Los tests del resto de la suite son mono-compañía a propósito (ver common.py).
Este archivo es la excepción necesaria: el bug solo se ve con el picking en OTRA
compañía. La segunda compañía la arma ``AccountTestInvoicingCommon`` con su
helper ``setup_other_company()`` (en 18 ya no viene hecha en el setUpClass como
el ``company_data_2`` de 17) — no se copia ninguna ``res.company``.

Son dos causas independientes, y las dos se cubren acá:

1. El camino nativo no muestra el picking NI con todas las compañías tildadas:
   se crea sin ``group_id``, y ``sale.order.picking_ids`` es un o2m sobre
   ``stock.picking.sale_id``, que el core computa desde ``group_id.sale_id``.
   El ``sale_line_id`` que el drop-ship sí lleva en el MOVE alcanza para que
   cuente como entregado, no para entrar al o2m.
2. La regla multi-compañía de ``stock.picking``
   (``[('company_id','in',company_ids)]``) filtra por ``self.env.companies``, o
   sea por las compañías TILDADAS en el selector (``allowed_company_ids`` del
   contexto), NO por las permitidas al usuario. El vendedor del mostrador tiene
   permiso sobre las dos compañías pero trabaja con su sucursal sola tildada.

Caso real que lo motivó: venta cargada en la sucursal sin stock y resuelta por
envío directo desde el depósito central. El vendedor veía la orden con su
entrega cancelada y ninguna salida, volvió a cargar la venta y se despacharon 6
unidades por una venta de 3.
"""
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockVisibilidadOrigen(MultiStockCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_origen = cls.setup_other_company()["company"]

        Warehouse = cls.env["stock.warehouse"].sudo()
        PickingType = cls.env["stock.picking.type"].sudo()

        # Se rehace el lado ORIGEN del mapeo en la SEGUNDA compañía: es lo que
        # reproduce la producción (origen = compañía padre, destino = sucursal).
        cls.wh_src_otra = Warehouse.create({
            "name": "Depósito Central (otra compañía)",
            "code": "MSOTR",
            "company_id": cls.company_origen.id,
        })
        cls.type_out_otra = PickingType.create({
            "name": "MS Despacho (otra compañía)",
            "code": "internal",
            "sequence_code": "MSOTO",
            "company_id": cls.company_origen.id,
            "warehouse_id": cls.wh_src_otra.id,
            "default_location_src_id": cls.wh_src_otra.lot_stock_id.id,
            "default_location_dest_id": cls.transit.id,
        })
        cls.type_dropship_otra = PickingType.create({
            "name": "MS Envío Directo (otra compañía)",
            "code": "outgoing",
            "sequence_code": "MSOTD",
            "company_id": cls.company_origen.id,
            "warehouse_id": cls.wh_src_otra.id,
            "default_location_src_id": cls.wh_src_otra.lot_stock_id.id,
            "default_location_dest_id": cls.customer_loc.id,
        })
        # El almacén DESTINO (y su tipo de recepción) siguen en cls.company.
        cls.wh_dest.write({
            "multi_stock_source_warehouse_id": cls.wh_src_otra.id,
            "multi_stock_out_type_id": cls.type_out_otra.id,
            "multi_stock_dropship_type_id": cls.type_dropship_otra.id,
        })

        # Vendedor del mostrador, calcado del usuario real de producción: tiene
        # PERMITIDAS las dos compañías, pero trabaja con la sucursal sola
        # tildada. Lo que lo ciega es allowed_company_ids del contexto, no el
        # permiso. Sin with_user + ese contexto el guard no se ejercita y el
        # test pasaría igual sin el sudo.
        cls.vendedor = cls.env["res.users"].sudo().create({
            "name": "Vendedor Sucursal",
            "login": "ms_vendedor_sucursal",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id, cls.company_origen.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("sales_team.group_sale_salesman").id,
                cls.env.ref("stock.group_stock_user").id,
            ])],
        })

    def _como_vendedor(self, record):
        """El record leído como lo lee el mostrador: usuario vendedor y SOLO la
        sucursal destino tildada en el selector de compañías."""
        return record.with_user(self.vendedor).with_context(
            allowed_company_ids=[self.company.id]
        )

    def _pickings_de(self, so):
        return self.env["stock.picking"].sudo().search([
            ("multi_stock_sale_id", "=", so.id)
        ])

    # ------------------------------------------------------------------ #
    #  R3 — envío directo desde la otra compañía                          #
    # ------------------------------------------------------------------ #
    def test_r3_expone_el_dropship_del_origen(self):
        prod = self._producto("Visib R3")
        self._stock(prod, 50.0, self.wh_src_otra)
        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()

        dropship = self._pickings_de(so)
        self.assertEqual(len(dropship), 1)
        self.assertEqual(
            dropship.company_id, self.company_origen,
            "el drop-ship debe vivir en la compañía del origen",
        )
        self.assertEqual(so.multi_stock_picking_count, 1)
        self.assertEqual(so.multi_stock_picking_ids.ids, dropship.ids)

    def test_el_core_no_lo_muestra_ni_con_las_dos_companias_tildadas(self):
        """Primera causa, la que NO se arregla tildando compañías: el picking se
        crea sin ``group_id``, así que ``sale_id`` (computado por el core desde
        ``group_id.sale_id``) queda en False y nunca entra a ``picking_ids``.

        Se lee con el usuario de la suite, que tiene las DOS compañías
        permitidas y tildadas: si aun así no aparece, el problema no se resuelve
        con configuración."""
        prod = self._producto("Visib core")
        self._stock(prod, 50.0, self.wh_src_otra)
        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()

        dropship = self._pickings_de(so)
        so_ambas = so.with_context(
            allowed_company_ids=[self.company.id, self.company_origen.id]
        )
        self.assertFalse(dropship.sale_id, "el drop-ship se crea sin group_id")
        self.assertNotIn(
            dropship.id, so_ambas.picking_ids.ids,
            "si el core ya lo mostrara, este módulo no haría falta",
        )
        self.assertIn(dropship.id, so_ambas.multi_stock_picking_ids.ids)

    # ------------------------------------------------------------------ #
    #  El caso que importa: leído por el mostrador                        #
    # ------------------------------------------------------------------ #
    def test_vendedor_del_destino_ve_el_dropship_del_origen(self):
        prod = self._producto("Visib vendedor")
        self._stock(prod, 50.0, self.wh_src_otra)
        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        dropship = self._pickings_de(so)

        # Premisa del bug: con solo la sucursal tildada ese remito NO existe
        # para el vendedor, aunque tenga PERMITIDA la compañía del origen. Si
        # esto dejara de valer, la regla cambió y el sudo sobra.
        self.assertIn(
            self.company_origen, self.vendedor.company_ids,
            "el vendedor tiene permitida la compañía del origen: lo que lo "
            "ciega es el selector, no el permiso",
        )
        self.assertFalse(
            self._como_vendedor(self.env["stock.picking"]).search([
                ("id", "=", dropship.id)
            ]),
            "con la sucursal sola tildada la regla debería ocultarle el remito",
        )
        with self.assertRaises(AccessError):
            self._como_vendedor(dropship).read(["name"])

        # Y aun así el pedido se lo muestra: es lo que aporta el sudo acotado.
        so_vendedor = self._como_vendedor(so)
        self.assertEqual(so_vendedor.multi_stock_picking_count, 1)
        self.assertEqual(so_vendedor.multi_stock_picking_ids.ids, dropship.ids)
        # El resumen se lee sin tocar el picking: son datos ya materializados.
        self.assertIn(dropship.name, so_vendedor.multi_stock_picking_resumen)

    def test_entrega_local_cancelada_pero_el_pedido_muestra_la_salida(self):
        """Reconstruye la pantalla que engañó al mostrador: la entrega del
        destino queda cancelada y la única salida real vive en la otra
        compañía."""
        prod = self._producto("Visib pantalla")
        self._stock(prod, 50.0, self.wh_src_otra)
        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()

        so_vendedor = self._como_vendedor(so)
        entregas_propias = so_vendedor.picking_ids
        self.assertTrue(
            all(p.state == "cancel" for p in entregas_propias),
            "la entrega del destino se cancela: por eso parecía que no salió nada",
        )
        self.assertEqual(so_vendedor.multi_stock_picking_count, 1)

    # ------------------------------------------------------------------ #
    #  R2 — traslado interno                                              #
    # ------------------------------------------------------------------ #
    def test_r2_expone_despacho_y_recepcion(self):
        prod = self._producto("Visib R2")
        self._stock(prod, 50.0, self.wh_src_otra)
        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        so_vendedor = self._como_vendedor(so)
        pickings = so_vendedor.multi_stock_picking_ids
        self.assertEqual(so_vendedor.multi_stock_picking_count, len(pickings))
        tipos = pickings.sudo().mapped("picking_type_id")
        self.assertIn(self.type_out_otra, tipos)
        self.assertIn(self.type_in, tipos)
        # El despacho es el que la regla le ocultaría (vive en el origen).
        despacho = pickings.sudo().filtered(
            lambda p: p.picking_type_id == self.type_out_otra
        )
        self.assertEqual(despacho.company_id, self.company_origen)
        self.assertIn(despacho.name, so_vendedor.multi_stock_picking_resumen)

    # ------------------------------------------------------------------ #
    #  Sin faltante: nada que mostrar                                     #
    # ------------------------------------------------------------------ #
    def test_sin_faltante_no_hay_nada_que_mostrar(self):
        prod = self._producto("Visib R1")
        self._stock(prod, 50.0, self.wh_dest)
        so = self._crear_venta(prod, 3.0, self.wh_dest)
        so.action_confirm()

        so_vendedor = self._como_vendedor(so)
        self.assertEqual(so_vendedor.multi_stock_picking_count, 0)
        self.assertFalse(so_vendedor.multi_stock_picking_ids)
        # La pestaña se esconde con count == 0.
        self.assertFalse(so_vendedor.multi_stock_picking_resumen)
