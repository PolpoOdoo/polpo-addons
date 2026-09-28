# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Control anti-negativo en tránsito (stock.picking._multi_stock_check_transit_disponible).

La recepción de un traslado inter-sucursal (Tránsito -> Destino) NO se puede
validar si la ubicación de tránsito no tiene stock físico suficiente, es decir,
si todavía no se validó el despacho del origen. Evita el stock negativo en
tránsito.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockTransito(MultiStockCommon):

    def _recepcion(self, so):
        return self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_in.id),
        ])

    def _despacho(self, so):
        return self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])

    def test_recepcion_sin_despacho_se_bloquea(self):
        # R2 confirmado: el despacho del origen NO se validó, el tránsito está
        # vacío. Intentar validar la recepción cargando cantidad debe bloquear.
        prod = self._producto("Anti-negativo")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        inn = self._recepcion(so)
        self.assertEqual(len(inn), 1)
        # Cargar la cantidad a recibir sin que haya stock en tránsito.
        inn.move_ids.quantity = 10.0
        with self.assertRaises(UserError):
            inn.sudo().button_validate()

    def test_recepcion_con_despacho_validado_ok(self):
        # Validado el despacho (origen -> tránsito), el tránsito tiene stock y la
        # recepción se valida sin disparar el guard.
        prod = self._producto("Cadena OK")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        out = self._despacho(so)
        out.sudo().action_assign()
        for ml in out.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        out.move_ids.picked = True
        out.sudo().button_validate()
        self.assertEqual(out.state, "done")

        inn = self._recepcion(so)
        inn.sudo().action_assign()
        for ml in inn.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        inn.move_ids.picked = True
        inn.sudo().button_validate()  # no debe levantar UserError
        self.assertEqual(inn.state, "done")

    def test_picking_sin_venta_ms_no_interviene(self):
        # Un picking normal (sin multi_stock_sale_id) no pasa por el guard.
        prod = self._producto("Normal")
        self._stock(prod, 5.0, self.wh_dest)
        so = self._crear_venta(prod, 5.0, self.wh_dest)  # R1, todo local
        so.action_confirm()
        delivery = so.picking_ids
        self.assertTrue(delivery)
        self.assertFalse(delivery.mapped("multi_stock_sale_id"))
        delivery.sudo().action_assign()
        for ml in delivery.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        delivery.move_ids.picked = True
        delivery.sudo().button_validate()  # no debe levantar UserError
        self.assertTrue(all(s == "done" for s in delivery.mapped("state")))
