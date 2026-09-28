# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests del motor de ruteo de stock (sale.order._multi_stock_apply y compañeros).

Cubre, sobre el FALTANTE real (medido por lo reservado, no por el campo):
- R1: todo disponible local -> no se genera traslado/drop-ship.
- Faltante sin modo elegido -> UserError (bloquea confirmación, rollback).
- R2 retira_despues: despacho (origen->tránsito) + recepción (tránsito->destino),
  encadenado; entrega del destino partida (lo local ahora, saldo diferido MTO).
- R3 envio_directo: drop-ship (origen->cliente) + entrega del destino reducida/cancelada.
- solo_existente: no-op (entrega estándar intacta).
- multi_stock_todo_origen: empuja TODA la línea por el origen aunque haya stock local.
- Almacén sin mapeo: comportamiento estándar, sin intervención.
- Caso inverso (mapeo en el otro almacén): el traslado se dispara en sentido contrario.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockRouting(MultiStockCommon):

    # ------------------------------------------------------------------ #
    #  R1 / bloqueo                                                       #
    # ------------------------------------------------------------------ #
    def test_r1_todo_local_no_genera_traslado(self):
        prod = self._producto("R1")
        self._stock(prod, 20.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)  # sin modo, no hace falta
        so.action_confirm()
        # No hay pickings de multi depósito.
        ms_pickings = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id)
        ])
        self.assertFalse(ms_pickings)
        # La entrega local existe y reservó la cantidad completa.
        line = so.order_line
        delivery = self._delivery_moves(line)
        self.assertEqual(sum(delivery.mapped("product_uom_qty")), 10.0)

    def test_faltante_sin_modo_levanta_usererror(self):
        prod = self._producto("Sin modo")
        # Sin stock local y sin elegir modo -> UserError bloqueante.
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        with self.assertRaises(UserError):
            so.action_confirm()

    def test_almacen_sin_mapeo_comportamiento_estandar(self):
        # Venta desde el ORIGEN (no mapeado): sin faltante artificial, sin pickings MS,
        # y no se levanta aunque falte stock (no aplica el módulo).
        prod = self._producto("Estándar")
        so = self._crear_venta(prod, 10.0, self.wh_src)
        so.action_confirm()  # no debe levantar UserError
        self.assertEqual(so.state, "sale")
        ms_pickings = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id)
        ])
        self.assertFalse(ms_pickings)

    # ------------------------------------------------------------------ #
    #  R2 — retira_despues                                                #
    # ------------------------------------------------------------------ #
    def test_r2_total_genera_despacho_y_recepcion(self):
        prod = self._producto("R2 total")
        self._stock(prod, 100.0, self.wh_src)  # stock en el origen, nada local
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        inn = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])
        self.assertEqual(len(out), 1, "debe haber un despacho origen->tránsito")
        self.assertEqual(len(inn), 1, "debe haber una recepción tránsito->destino")

        # Despacho: origen/existencias -> tránsito, compañía del origen.
        out_move = out.move_ids
        self.assertEqual(out_move.location_id, self.wh_src.lot_stock_id)
        self.assertEqual(out_move.location_dest_id, self.transit)
        self.assertEqual(out_move.product_uom_qty, 10.0)
        self.assertEqual(out.company_id, self.wh_src.company_id)

        # Recepción: tránsito -> destino/existencias, compañía del destino.
        in_move = inn.move_ids
        self.assertEqual(in_move.location_id, self.transit)
        self.assertEqual(in_move.location_dest_id, self.wh_dest.lot_stock_id)
        self.assertEqual(in_move.product_uom_qty, 10.0)
        self.assertEqual(inn.company_id, self.wh_dest.company_id)

        # Ambos confirmados, ninguno validado.
        self.assertNotIn(out.state, ("done", "cancel"))
        self.assertNotIn(inn.state, ("done", "cancel"))

    def test_r2_total_difiere_entrega_encadenada_mto(self):
        # Sin nada local: el move de entrega entero pasa a MTO encadenado a la recepción.
        prod = self._producto("R2 difiere")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        line = so.order_line
        delivery = self._delivery_moves(line)
        self.assertEqual(len(delivery), 1)
        deferred = delivery[0]
        self.assertEqual(deferred.product_uom_qty, 10.0)
        self.assertEqual(deferred.procure_method, "make_to_order")
        # Encadenado: su origen es el move de la recepción.
        recep = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ]).move_ids
        self.assertIn(recep, deferred.move_orig_ids)
        self.assertIn(deferred, recep.move_dest_ids)
        # No reservado (waiting): la recepción todavía no se validó.
        self.assertNotEqual(deferred.state, "assigned")

    def test_r2_parcial_entrega_local_ahora_y_difiere_saldo(self):
        # Caso del analista: 6 de 10 disponibles local. 6 se entregan ahora (picking
        # propio reservado), 4 vía traslado y diferidos en picking SEPARADO.
        prod = self._producto("R2 parcial")
        self._stock(prod, 6.0, self.wh_dest)
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        line = so.order_line

        # Traslado por el faltante real (4), no por los 10.
        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        self.assertEqual(out.move_ids.product_uom_qty, 4.0)

        delivery = self._delivery_moves(line)
        cant_local = delivery.filtered(lambda m: m.procure_method == "make_to_stock")
        cant_dif = delivery.filtered(lambda m: m.procure_method == "make_to_order")
        self.assertEqual(sum(cant_local.mapped("product_uom_qty")), 6.0)
        self.assertEqual(sum(cant_dif.mapped("product_uom_qty")), 4.0)
        # La porción local quedó reservada (entregable ahora).
        self.assertEqual(sum(cant_local.mapped("quantity")), 6.0)
        # El saldo diferido va en un picking distinto al de la porción local.
        self.assertNotEqual(cant_local.picking_id, cant_dif.picking_id)
        # El diferido está encadenado a la recepción.
        recep = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ]).move_ids
        self.assertIn(recep, cant_dif.move_orig_ids)

    def test_r2_cadena_completa_valida_y_entrega_saldo(self):
        # Validar despacho -> recepción -> el saldo diferido se reserva y entrega.
        prod = self._producto("R2 cadena")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        inn = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])
        # Despacho: reservo desde el origen y valido.
        out.sudo().action_assign()
        for ml in out.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        out.move_ids.picked = True
        out.sudo().button_validate()
        self.assertEqual(out.state, "done")
        # La mercadería está en tránsito; valido la recepción.
        inn.sudo().action_assign()
        self.assertEqual(inn.state, "assigned")
        for ml in inn.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        inn.move_ids.picked = True
        inn.sudo().button_validate()
        self.assertEqual(inn.state, "done")

        # El saldo diferido (encadenado) ahora puede reservarse en el destino.
        line = so.order_line
        deferred = self._delivery_moves(line)
        deferred.sudo()._action_assign()
        self.assertEqual(sum(deferred.mapped("quantity")), 10.0)

    # ------------------------------------------------------------------ #
    #  R3 — envio_directo                                                 #
    # ------------------------------------------------------------------ #
    def test_r3_total_dropship_y_cancela_entrega_destino(self):
        prod = self._producto("R3 total")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        line = so.order_line

        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        self.assertEqual(len(ds), 1)
        ds_move = ds.move_ids
        self.assertEqual(ds_move.location_id, self.wh_src.lot_stock_id)
        self.assertEqual(ds_move.location_dest_id.usage, "customer")
        self.assertEqual(ds_move.product_uom_qty, 10.0)
        self.assertEqual(ds.company_id, self.wh_src.company_id)
        # El move del drop-ship cuenta como entrega de la línea.
        self.assertEqual(ds_move.sale_line_id, line)

        # La entrega del destino por esos 10 se canceló (toda la línea es R3).
        delivery_destino = line.move_ids.filtered(
            lambda m: m.location_dest_id.usage == "customer"
            and m.picking_id.picking_type_id != self.type_dropship
        )
        self.assertTrue(all(m.state == "cancel" for m in delivery_destino))

    def test_r3_parcial_reduce_entrega_destino(self):
        # 6 local + 4 por envío directo: la entrega del destino baja de 10 a 6.
        prod = self._producto("R3 parcial")
        self._stock(prod, 6.0, self.wh_dest)
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        line = so.order_line

        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        self.assertEqual(ds.move_ids.product_uom_qty, 4.0)

        # Entrega del destino (no drop-ship) reducida a 6.
        delivery_destino = line.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
            and m.location_dest_id.usage == "customer"
            and m.picking_id.picking_type_id != self.type_dropship
        )
        self.assertEqual(sum(delivery_destino.mapped("product_uom_qty")), 6.0)

    # ------------------------------------------------------------------ #
    #  solo_existente                                                     #
    # ------------------------------------------------------------------ #
    def test_solo_existente_no_interviene(self):
        prod = self._producto("Solo existente")
        self._stock(prod, 6.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="solo_existente")
        so.action_confirm()
        # No se generó ningún picking de multi depósito.
        ms_pickings = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id)
        ])
        self.assertFalse(ms_pickings)
        # La entrega del destino mantiene la demanda completa (backorder nativo al validar).
        line = so.order_line
        delivery = self._delivery_moves(line)
        self.assertEqual(sum(delivery.mapped("product_uom_qty")), 10.0)

    # ------------------------------------------------------------------ #
    #  todo_origen                                                        #
    # ------------------------------------------------------------------ #
    def test_todo_origen_empuja_toda_la_linea(self):
        # Hay stock local de sobra, pero todo_origen fuerza el faltante = total.
        prod = self._producto("Todo origen")
        self._stock(prod, 100.0, self.wh_dest)
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(
            prod, 10.0, self.wh_dest, modo="retira_despues", todo_origen=True
        )
        so.action_confirm()
        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        # El traslado mueve los 10 completos, no 0.
        self.assertEqual(out.move_ids.product_uom_qty, 10.0)
        # La entrega del destino quedó toda diferida (MTO), nada local.
        line = so.order_line
        delivery = self._delivery_moves(line)
        self.assertTrue(all(m.procure_method == "make_to_order" for m in delivery))

    # ------------------------------------------------------------------ #
    #  Cancelación de la venta -> cancela traslados/drop-ship (bug #18)   #
    # ------------------------------------------------------------------ #
    def test_cancelar_venta_cancela_pickings_r2(self):
        # Bug #18: al cancelar la venta, los pickings inter-sucursal (despacho +
        # recepción) NO se cancelaban (no comparten el grupo de aprovisionamiento
        # de la venta) y quedaban huérfanos. Deben quedar en 'cancel'.
        prod = self._producto("R2 cancel")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        inn = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])
        self.assertNotIn(out.state, ("done", "cancel"))
        self.assertNotIn(inn.state, ("done", "cancel"))

        so._action_cancel()

        self.assertEqual(so.state, "cancel")
        self.assertEqual(out.state, "cancel", "el despacho debe cancelarse con la venta")
        self.assertEqual(inn.state, "cancel", "la recepción debe cancelarse con la venta")
        # La entrega del destino diferida (encadenada) también queda cancelada.
        delivery = so.order_line.move_ids.filtered(
            lambda m: m.location_dest_id.usage == "customer")
        self.assertTrue(all(m.state == "cancel" for m in delivery))

    def test_cancelar_venta_cancela_dropship_r3(self):
        prod = self._producto("R3 cancel")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        self.assertNotIn(ds.state, ("done", "cancel"))

        so._action_cancel()

        self.assertEqual(ds.state, "cancel", "el drop-ship debe cancelarse con la venta")

    def test_cancelar_no_toca_picking_ya_validado(self):
        # El despacho ya validado (mercadería movida) NO se cancela al cancelar
        # la venta: solo se cancelan los pendientes.
        prod = self._producto("R2 done")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        out.sudo().action_assign()
        for ml in out.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        out.move_ids.picked = True
        out.sudo().button_validate()
        self.assertEqual(out.state, "done")

        so._action_cancel()

        # El despacho validado sigue en done; la recepción pendiente se cancela.
        self.assertEqual(out.state, "done")
        inn = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])
        self.assertEqual(inn.state, "cancel")

    # ------------------------------------------------------------------ #
    #  Caso inverso (direccionalidad)                                     #
    # ------------------------------------------------------------------ #
    def test_caso_inverso_mapeo_en_el_otro_almacen(self):
        # Mapeo el ORIGEN apuntando al DESTINO: una venta desde el origen ahora
        # dispara el traslado en sentido contrario (destino -> origen).
        Location = self.env["stock.location"].sudo()
        PickingType = self.env["stock.picking.type"].sudo()
        transit2 = Location.create({
            "name": "Tránsito inverso",
            "usage": "transit",
            "company_id": False,
        })
        out2 = PickingType.create({
            "name": "MS Despacho inv",
            "code": "internal",
            "sequence_code": "MSOUTI",
            "company_id": self.company.id,
            "warehouse_id": self.wh_dest.id,
            "default_location_src_id": self.wh_dest.lot_stock_id.id,
            "default_location_dest_id": transit2.id,
        })
        in2 = PickingType.create({
            "name": "MS Recepción inv",
            "code": "internal",
            "sequence_code": "MSINI",
            "company_id": self.company.id,
            "warehouse_id": self.wh_src.id,
            "default_location_src_id": transit2.id,
            "default_location_dest_id": self.wh_src.lot_stock_id.id,
        })
        ds2 = PickingType.create({
            "name": "MS Envío inv",
            "code": "outgoing",
            "sequence_code": "MSDSI",
            "company_id": self.company.id,
            "warehouse_id": self.wh_dest.id,
            "default_location_src_id": self.wh_dest.lot_stock_id.id,
            "default_location_dest_id": self.customer_loc.id,
        })
        self.wh_src.write({
            "multi_stock_source_warehouse_id": self.wh_dest.id,
            "multi_stock_transit_location_id": transit2.id,
            "multi_stock_out_type_id": out2.id,
            "multi_stock_in_type_id": in2.id,
            "multi_stock_dropship_type_id": ds2.id,
        })

        prod = self._producto("Inverso")
        # Stock en el DESTINO (que ahora es el origen del mapeo inverso).
        self._stock(prod, 100.0, self.wh_dest)
        # Venta desde wh_src (que ahora vende sin stock).
        so = self._crear_venta(prod, 10.0, self.wh_src, modo="retira_despues")
        so.action_confirm()

        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", out2.id),
        ])
        self.assertEqual(len(out), 1)
        # El despacho sale del wh_dest (origen del mapeo inverso) hacia el tránsito2.
        self.assertEqual(out.move_ids.location_id, self.wh_dest.lot_stock_id)
        self.assertEqual(out.move_ids.location_dest_id, transit2)
