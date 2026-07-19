# Copyright 2026 QEI SRL (Polpo)
# License OPL-1 (Odoo Proprietary License v1.0).
"""Reabastecimiento inter-almacén: al validar el despacho Origen -> Tránsito se
auto-genera la recepción Tránsito -> Destino precargada y pendiente de validar.

Cubre el caso "pedir mercadería a depósito" (traslado manual, sin venta): la
mercadería se ingresa UNA sola vez en el despacho y la recepción es solo validar
lo que llega. Verifica también que el flujo de venta no duplica la recepción.
"""

from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockReabastecimiento(MultiStockCommon):
    def _despacho_manual(self, product, qty):
        """Crea y valida un despacho manual Origen(Central) -> Tránsito, como lo
        arma hoy el operario al pedir mercadería a depósito."""
        picking = (
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
                                "name": product.display_name,
                                "product_id": product.id,
                                "product_uom_qty": qty,
                                "product_uom": product.uom_id.id,
                                "location_id": self.wh_src.lot_stock_id.id,
                                "location_dest_id": self.transit.id,
                            },
                        )
                    ],
                }
            )
        )
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _validar(self, picking, qty=None):
        """Valida un picking cargando la cantidad hecha (toda la demanda si no se
        pasa qty)."""
        for ml in picking.move_ids.move_line_ids:
            ml.quantity = qty if qty is not None else ml.move_id.product_uom_qty
        picking.move_ids.picked = True
        picking.sudo().button_validate()

    def _recepcion_generada(self, despacho):
        return (
            self.env["stock.picking"]
            .sudo()
            .search([("multi_stock_dispatch_id", "=", despacho.id)])
        )

    def test_despacho_manual_genera_recepcion_pendiente(self):
        prod = self._producto("Reabastecimiento")
        self._stock(prod, 100.0, self.wh_src)

        despacho = self._despacho_manual(prod, 10.0)
        self._validar(despacho)
        self.assertEqual(despacho.state, "done")

        recepcion = self._recepcion_generada(despacho)
        self.assertEqual(len(recepcion), 1, "Debe generarse una única recepción")
        # Precargada con lo despachado, pendiente de validar (no done/draft).
        self.assertNotIn(recepcion.state, ("done", "cancel", "draft"))
        self.assertEqual(recepcion.picking_type_id, self.type_in)
        self.assertEqual(recepcion.location_id, self.transit)
        self.assertEqual(recepcion.location_dest_id, self.wh_dest.lot_stock_id)
        self.assertEqual(len(recepcion.move_ids), 1)
        self.assertEqual(recepcion.move_ids.product_id, prod)
        self.assertEqual(recepcion.move_ids.product_uom_qty, 10.0)

        # Validar la recepción baja la mercadería al destino (sin re-tipear).
        self._validar(recepcion)
        self.assertEqual(recepcion.state, "done")
        disponible_dest = prod.with_context(
            location=self.wh_dest.lot_stock_id.id
        ).qty_available
        self.assertEqual(disponible_dest, 10.0)

    def test_despacho_parcial_recepcion_con_lo_despachado(self):
        # Depósito despacha menos de lo pedido: la recepción se precarga con lo
        # efectivamente despachado (lo que hay en tránsito), no con la demanda.
        prod = self._producto("Reabastecimiento parcial")
        self._stock(prod, 100.0, self.wh_src)

        despacho = self._despacho_manual(prod, 10.0)
        # Despacha 6 y NO crea backorder (entrega lo existente y cierra).
        for ml in despacho.move_ids.move_line_ids:
            ml.quantity = 6.0
        despacho.move_ids.picked = True
        Wizard = self.env["stock.backorder.confirmation"]
        res = despacho.sudo().button_validate()
        if isinstance(res, dict) and res.get("res_model") == Wizard._name:
            Wizard.with_context(**res["context"]).create({}).process_cancel_backorder()
        self.assertEqual(despacho.state, "done")

        recepcion = self._recepcion_generada(despacho)
        self.assertEqual(len(recepcion), 1)
        self.assertEqual(recepcion.move_ids.product_uom_qty, 6.0)

    def test_venta_retira_despues_no_duplica_recepcion(self):
        # El flujo de venta ya crea su recepción (multi_stock_sale_id); validar
        # el despacho NO debe generar una segunda.
        prod = self._producto("Venta sin duplicar")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()

        despacho = (
            self.env["stock.picking"]
            .sudo()
            .search(
                [
                    ("multi_stock_sale_id", "=", so.id),
                    ("picking_type_id", "=", self.type_out.id),
                ]
            )
        )
        self.assertEqual(len(despacho), 1)
        self._validar(despacho)
        self.assertEqual(despacho.state, "done")

        recepciones = (
            self.env["stock.picking"]
            .sudo()
            .search(
                [
                    ("picking_type_id", "=", self.type_in.id),
                    ("location_id", "=", self.transit.id),
                    ("location_dest_id", "=", self.wh_dest.lot_stock_id.id),
                    "|",
                    ("multi_stock_sale_id", "=", so.id),
                    ("multi_stock_dispatch_id", "=", despacho.id),
                ]
            )
        )
        self.assertEqual(len(recepciones), 1, "No debe duplicar la recepción")
