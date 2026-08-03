# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Una orden interceptada (no confirmada) no dispara multi depósito.

Otros módulos (riesgo crediticio / sale_financial_risk) interceptan
``action_confirm`` devolviendo un wizard SIN llamar a super(): la orden queda
en borrador y sin movimientos. Antes multi depósito medía el faltante igual
sobre esa orden draft (reservado 0) y lanzaba un UserError "faltan <cantidad
completa>" cuyo rollback además se tragaba el wizard del interceptor.
"""
from unittest.mock import patch

from odoo.addons.sale.models.sale_order import SaleOrder as SaleBase
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockRiesgoIntercepta(MultiStockCommon):

    def test_orden_no_confirmada_no_aplica_multi_deposito(self):
        # Producto sin stock local: si multi depósito se ejecutara, mediría un
        # faltante total y fallaría.
        prod = self._producto("Interceptada")
        so = self._crear_venta(prod, 10.0, self.wh_dest)

        # Simula el interceptor de riesgo: action_confirm devuelve un wizard y
        # deja la orden en borrador (no llama a super() del core).
        wizard = {"type": "ir.actions.act_window", "res_model": "partner.risk.exceeded.wiz"}
        with patch.object(type(so), "_multi_stock_apply") as spy:
            with patch.object(SaleBase, "action_confirm", lambda self: wizard):
                res = so.action_confirm()

        self.assertEqual(res, wizard, "Se debe devolver el wizard del interceptor.")
        self.assertEqual(so.state, "draft", "La orden interceptada sigue en borrador.")
        spy.assert_not_called()
        self.assertFalse(
            so.order_line.move_ids,
            "Sin confirmar no debe generarse ningún movimiento de stock.",
        )

    def test_orden_confirmada_si_aplica_multi_deposito(self):
        # Control positivo: con la orden efectivamente confirmada, multi depósito
        # sí corre (hay stock en el origen, así que resuelve sin faltante).
        prod = self._producto("Confirmada")
        self._stock(prod, 50.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest)

        with patch.object(type(so), "_multi_stock_apply") as spy:
            so.action_confirm()

        self.assertEqual(so.state, "sale")
        spy.assert_called_once()
