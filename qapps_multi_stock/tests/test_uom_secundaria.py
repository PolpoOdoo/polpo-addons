# Copyright 2026 QEI SRL (Polpo)
# License OPL-1 (Odoo Proprietary License v1.0).
"""Regresión — UoM secundaria en el ruteo multi depósito.

El faltante se medía como `qty_total - reservado_local`, donde `qty_total`
(= line.product_uom_qty) está en la UoM de la LÍNEA (ej. docenas) pero
`reservado_local` (= sum(move.quantity)) está en la UoM del MOVE (la de
referencia del producto, ej. unidades). La resta mezclaba unidades y descuadraba
el routing cuando había stock local parcial y la línea usaba una UoM distinta a
la del producto. Mismo defecto en `_multi_stock_split_delivery_defer` y
`_multi_stock_reduce_delivery`. Fix: convertir a la UoM de la línea (identidad
cuando UoM de línea == UoM del producto, el caso normal).
"""
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestUomSecundaria(MultiStockCommon):

    def test_r2_parcial_uom_docena(self):
        # Venta de 3 docenas (=36 u). Local: 24 u = 2 docenas. Origen: de sobra.
        # Faltante real: 1 docena. Debe generar el traslado por 1 docena.
        prod = self._producto("UoM R2 parcial")
        self._stock(prod, 24.0, self.wh_dest)
        self._stock(prod, 100.0, self.wh_src)
        docena = self.env.ref("uom.product_uom_dozen")

        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="retira_despues")
        so.order_line.product_uom = docena.id
        so.action_confirm()

        out = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_out.id),
        ])
        self.assertEqual(len(out), 1,
            "debe generarse el traslado por el faltante (1 docena)")
        self.assertEqual(out.move_ids.product_uom, docena,
            "el move del traslado debe quedar en la UoM de la línea")
        self.assertEqual(out.move_ids.product_uom_qty, 1.0,
            "el faltante trasladado debe ser 1 docena")

        # La entrega del destino se parte: ~2 docenas locales ahora, 1 diferida.
        line = so.order_line
        delivery = self._delivery_moves(line)
        total_doc = sum(
            m.product_uom._compute_quantity(m.product_uom_qty, docena)
            for m in delivery
        )
        self.assertAlmostEqual(total_doc, 3.0, places=2,
            msg="la entrega partida debe conservar las 3 docenas vendidas")

    def test_r3_total_uom_docena_cancela_entrega_destino(self):
        # 3 docenas, sin stock local -> R3 total -> drop-ship por 3 docenas y la
        # entrega del destino se cancela entera.
        prod = self._producto("UoM R3 total")
        self._stock(prod, 100.0, self.wh_src)
        docena = self.env.ref("uom.product_uom_dozen")

        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.order_line.product_uom = docena.id
        so.action_confirm()
        line = so.order_line

        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        self.assertEqual(ds.move_ids.product_uom_qty, 3.0,
            "el drop-ship debe ser por 3 docenas")
        delivery_destino = line.move_ids.filtered(
            lambda m: m.location_dest_id.usage == "customer"
            and m.picking_id.picking_type_id != self.type_dropship)
        self.assertTrue(all(m.state == "cancel" for m in delivery_destino),
            "la entrega del destino debe cancelarse en R3 total")

    def test_r3_parcial_uom_docena_reduce_entrega_destino(self):
        # 3 docenas, 12 u (=1 docena) local -> drop-ship por 2 docenas, entrega
        # del destino reducida a 1 docena.
        prod = self._producto("UoM R3 parcial")
        self._stock(prod, 12.0, self.wh_dest)   # 1 docena local
        self._stock(prod, 100.0, self.wh_src)
        docena = self.env.ref("uom.product_uom_dozen")

        so = self._crear_venta(prod, 3.0, self.wh_dest, modo="envio_directo")
        so.order_line.product_uom = docena.id
        so.action_confirm()
        line = so.order_line

        ds = self.env["stock.picking"].search([
            ("multi_stock_sale_id", "=", so.id),
            ("picking_type_id", "=", self.type_dropship.id),
        ])
        self.assertEqual(ds.move_ids.product_uom_qty, 2.0,
            "el drop-ship debe cubrir el faltante de 2 docenas")
        delivery_destino = line.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
            and m.location_dest_id.usage == "customer"
            and m.picking_id.picking_type_id != self.type_dropship)
        total_doc = sum(
            m.product_uom._compute_quantity(m.product_uom_qty, docena)
            for m in delivery_destino)
        self.assertAlmostEqual(total_doc, 1.0, places=2,
            msg="la entrega del destino debe quedar en 1 docena")
