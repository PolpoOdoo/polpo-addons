# -*- coding: utf-8 -*-
"""Regresión: una línea de venta con cantidad NEGATIVA (devolución del mostrador)
no debería generar un traslado/dropship inter-sucursal de multi_stock.
"""
from odoo.tests import tagged
from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockCantidadNegativa(MultiStockCommon):

    def test_cantidad_negativa_no_genera_traslado(self):
        prod = self._producto("Neg")
        self._stock(prod, 100.0, self.wh_src)
        so = self._crear_venta(prod, -2.0, self.wh_dest, modo="retira_despues")
        so.action_confirm()
        ms = self.env["stock.picking"].search([("multi_stock_sale_id", "=", so.id)])
        self.assertFalse(
            ms,
            "una línea de cantidad negativa (devolución) generó traslado inter-sucursal: %s"
            % ms.mapped("name"))
