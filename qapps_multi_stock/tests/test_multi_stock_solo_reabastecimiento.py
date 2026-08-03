# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Modo "solo reabastecimiento" (multi_stock_solo_reabastecimiento).

El almacén participa del reabastecimiento inter-almacén (recepción auto-generada
al validar el despacho, SPEC 4.6) pero NO interviene la venta: una venta desde
ese almacén con faltante sigue el flujo nativo de Odoo, sin exigir el selector de
cumplimiento ni generar traslado/drop-ship automáticos.

Caso Palermo: la sucursal vende con su propio stock y se abastece de la planta
por traslado manual; no quiere el flujo de venta multi-depósito de EI.
"""

from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockSoloReabastecimiento(MultiStockCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # El mapeo del destino ya viene de common; solo activamos el modo.
        cls.wh_dest.multi_stock_solo_reabastecimiento = True

    def test_tiene_faltante_false_en_solo_reabastecimiento(self):
        # Con faltante real (sin stock en el destino) el selector NO se habilita.
        prod = self._producto("Solo reab - faltante")
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertGreater(line.multi_stock_faltante, 0.0)
        self.assertFalse(
            line.multi_stock_tiene_faltante,
            "En modo solo reabastecimiento no debe pedir cumplimiento del faltante",
        )

    def test_venta_con_faltante_no_bloquea_ni_genera_documentos(self):
        # Sin stock local y SIN elegir modo, la venta debe confirmar igual (flujo
        # nativo) y NO generar traslado/drop-ship inter-almacén.
        prod = self._producto("Solo reab - venta")
        so = self._crear_venta(prod, 10.0, self.wh_dest)  # sin modo

        so.action_confirm()  # no debe levantar UserError

        self.assertEqual(so.state, "sale")
        inter_almacen = (
            self.env["stock.picking"]
            .sudo()
            .search([("multi_stock_sale_id", "=", so.id)])
        )
        self.assertFalse(
            inter_almacen, "No debe generar documentos inter-almacén en la venta"
        )
        # La entrega nativa al cliente existe (queda esperando disponibilidad).
        entrega = self._delivery_moves(so.order_line)
        self.assertTrue(entrega, "Debe existir la entrega nativa al cliente")

    def test_reabastecimiento_sigue_generando_recepcion(self):
        # El flag NO apaga la sección 4.6: al validar el despacho manual hacia el
        # tránsito se auto-genera la recepción en el destino.
        prod = self._producto("Solo reab - traslado")
        self._stock(prod, 100.0, self.wh_src)

        despacho = (
            self.env["stock.picking"]
            .sudo()
            .create(
                {
                    "picking_type_id": self.type_out.id,
                    "location_id": self.wh_src.lot_stock_id.id,
                    "location_dest_id": self.transit.id,
                    "move_ids": [
                        (
                            0,
                            0,
                            {
                                "name": prod.display_name,
                                "product_id": prod.id,
                                "product_uom_qty": 10.0,
                                "product_uom": prod.uom_id.id,
                                "location_id": self.wh_src.lot_stock_id.id,
                                "location_dest_id": self.transit.id,
                            },
                        )
                    ],
                }
            )
        )
        despacho.action_confirm()
        despacho.action_assign()
        for ml in despacho.move_ids.move_line_ids:
            ml.quantity = ml.move_id.product_uom_qty
        despacho.move_ids.picked = True
        despacho.sudo().button_validate()
        self.assertEqual(despacho.state, "done")

        recepcion = (
            self.env["stock.picking"]
            .sudo()
            .search([("multi_stock_dispatch_id", "=", despacho.id)])
        )
        self.assertEqual(len(recepcion), 1, "Debe auto-generarse la recepción")
        self.assertEqual(recepcion.picking_type_id, self.type_in)
        self.assertEqual(recepcion.location_dest_id, self.wh_dest.lot_stock_id)
        self.assertEqual(recepcion.move_ids.product_uom_qty, 10.0)
