# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests del predicado de auto-validación (sale.order._multi_stock_picking_auto_validable).

Un picking es auto-validable SOLO si:
- estado no done/cancel,
- company_id == order.company_id,
- todos sus moves van a usage='customer',
- su location_id no es el tránsito,
- está totalmente reservado (move.quantity >= product_uom_qty).

Los pickings inter-almacén (despacho/recepción) y el saldo diferido en waiting
deben devolver False. Esto lo usa el auto-validate de polpo.
"""
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockAutoValidable(MultiStockCommon):

    def test_entrega_local_reservada_es_auto_validable(self):
        prod = self._producto("Auto local")
        self._stock(prod, 20.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        so.action_confirm()
        delivery = self._delivery_moves(so.order_line).picking_id
        delivery.sudo().action_assign()
        self.assertTrue(so._multi_stock_picking_auto_validable(delivery))

    def test_entrega_no_reservada_no_es_auto_validable(self):
        # solo_existente con stock parcial: la entrega no reserva el total -> False.
        prod = self._producto("Parcial no auto")
        self._stock(prod, 6.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="solo_existente")
        so.action_confirm()
        delivery = self._delivery_moves(so.order_line).picking_id
        delivery.sudo().action_assign()
        # Reservó 6 de 10 -> no totalmente disponible.
        self.assertFalse(so._multi_stock_picking_auto_validable(delivery))

    def test_despacho_a_transito_no_es_auto_validable(self):
        # El despacho R2 va a tránsito (no a cliente) -> nunca auto-validable.
        prod = self._producto("Despacho no auto")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        self.assertFalse(so._multi_stock_picking_auto_validable(out))

    def test_recepcion_desde_transito_no_es_auto_validable(self):
        # La recepción R2 viene del tránsito -> location_id == tránsito -> False.
        prod = self._producto("Recepción no auto")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        inn = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])
        self.assertFalse(so._multi_stock_picking_auto_validable(inn))

    def test_saldo_diferido_waiting_no_es_auto_validable(self):
        # El saldo diferido está en waiting (MTO, sin reservar) -> no auto-validable.
        prod = self._producto("Diferido no auto")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        deferred_picking = self._delivery_moves(so.order_line).picking_id
        self.assertFalse(so._multi_stock_picking_auto_validable(deferred_picking))

    def test_dropship_no_es_auto_validable(self):
        # El drop-ship va a cliente pero sale del ORIGEN; en producción el origen
        # es OTRA compañía, y el predicado lo descarta por la guarda
        # ``picking.company_id != self.company_id``. El common es mono-compañía
        # por regla del proyecto (no se copia res.company), así que aquí origen y
        # venta comparten compañía y esa guarda no aplica: el otro discriminador
        # real del predicado es la disponibilidad (move totalmente reservado).
        #
        # OJO: el drop-ship se crea con _multi_stock_gen_dropship() que llama
        # action_confirm(), y con stock en wh_src (100) y reservation_method
        # 'at_confirm' (default outgoing) el move queda RESERVADO al confirmar
        # (move.quantity == product_uom_qty). Por eso, en este fixture mono-
        # compañía, hay que des-reservar explícitamente para reflejar el caso de
        # un drop-ship pendiente (no disponible) que NO debe auto-validarse.
        prod = self._producto("Dropship no auto")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="envio_directo")
        so.action_confirm()
        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        # Des-reservar: el drop-ship queda pendiente (no totalmente disponible).
        ds.move_ids._do_unreserve()
        self.assertFalse(so._multi_stock_picking_auto_validable(ds))

    def test_picking_done_no_es_auto_validable(self):
        prod = self._producto("Done no auto")
        self._stock(prod, 20.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        so.action_confirm()
        delivery = self._delivery_moves(so.order_line).picking_id
        delivery.sudo().action_assign()
        for ml in delivery.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        delivery.move_ids.picked = True
        delivery.sudo().button_validate()
        self.assertEqual(delivery.state, "done")
        self.assertFalse(so._multi_stock_picking_auto_validable(delivery))
