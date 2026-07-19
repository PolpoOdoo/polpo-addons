# -*- coding: utf-8 -*-
"""Regresión: retención sobre factura en MONEDA EXTRANJERA (USD).
El asiento de reclasificación (account_move.py) crea las líneas con 'debit'/
'credit' = retention.amount pero SIN currency_id ni amount_currency. Si la
factura es en USD, amount está en USD pero la línea se contabiliza en moneda
compañía → descuadre cambiario y el residual no baja el monto correcto.
"""
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestRetencionMonedaExtranjera(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.iva_22 = cls.env["account.tax"].create({
            "name": "IVA 22 usd probe", "amount_type": "percent", "amount": 22.0,
            "type_tax_use": "sale", "company_id": cls.company_data["company"].id,
        })
        cls.cuenta_retencion = cls.env["account.account"].create({
            "name": "Ret garantia usd", "code": "RETUSD1",
            "account_type": "liability_current",
            "company_ids": [(6, 0, [cls.company_data["company"].id])],
        })
        cls.company_data["company"].retention_warranty_account_id = cls.cuenta_retencion.id
        # v18: AccountTestInvoicingCommon.currency_data ya no existe; se arma una
        # moneda extranjera con setup_other_currency (la tasa no afecta esta
        # aserción: el amount_currency es el 10% de 1000 en la moneda de la factura).
        cls.foreign = cls.setup_other_currency("EUR")

    def test_retencion_factura_usd_lleva_moneda(self):
        move = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000.0],
            taxes=self.iva_22, currency=self.foreign)
        self.assertEqual(move.currency_id, self.foreign)
        self.env["qapps.retenciones.cce"].create({
            "move_id": move.id, "application_type": "retention",
            "base_calculation": "base", "percentage": 10.0,
        })
        residual_antes = move.amount_residual  # en USD
        move.action_post()

        reclass = self.env["account.move"].search([
            ("ref", "=like", "Retenciones %"), ("move_type", "=", "entry"),
            ("partner_id", "=", move.partner_id.id)], limit=1)
        self.assertTrue(reclass, "no se generó el asiento de reclasificación")
        linea_ret = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_retencion)
        # La línea de retención debe estar en la moneda de la factura (USD) con
        # su amount_currency, no en moneda compañía sin moneda.
        self.assertEqual(
            linea_ret.currency_id, move.currency_id,
            "la línea de retención no lleva la moneda de la factura (currency_id=%s)"
            % linea_ret.currency_id.name)
        self.assertAlmostEqual(
            abs(linea_ret.amount_currency), 100.0, places=2,
            msg="amount_currency=%s (esperado 100 USD)" % linea_ret.amount_currency)
