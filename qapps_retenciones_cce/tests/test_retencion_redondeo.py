# -*- coding: utf-8 -*-
"""Regresión — doble redondeo con VARIAS retenciones en moneda extranjera.

Cada retención se convertía a moneda compañía y se redondeaba por separado, así
que con 2+ retenciones USD `sum(round(amount_i·TC))` podía diferir de
`round(sum·TC)` (hasta 0.01) y dejar el residual de la factura descuadrado en
moneda compañía contra el receivable (valuado con un único redondeo). El fix
reparte ese centavo a la retención de mayor monto para que la suma coincida con
la conversión única del total, manteniendo el asiento balanceado.

Escenario forzado: moneda con TC=3, dos retenciones de 0.05 c/u →
0.05/3 = 0.0167 → 0.02 cada una = 0.04 ; total 0.10/3 = 0.0333 → 0.03.
"""
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestRetencionRedondeoVarias(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)
        cls.company = cls.company_data["company"]
        cls.iva_22 = cls.env["account.tax"].create({
            "name": "IVA 22 round multi", "amount_type": "percent", "amount": 22.0,
            "type_tax_use": "sale", "company_id": cls.company.id,
        })
        cls.cuenta_retencion = cls.env["account.account"].create({
            "name": "Ret garantia round", "code": "RETRND2",
            "account_type": "liability_current", "company_id": cls.company.id,
        })
        cls.company.retention_warranty_account_id = cls.cuenta_retencion.id
        # Moneda con TC "feo" (1 compañía = 3 feo) que fuerza el doble redondeo.
        cls.feo = cls.env["res.currency"].create({
            "name": "DBR", "symbol": "DBR", "rounding": 0.01,
        })
        cls.env["res.currency.rate"].create({
            "currency_id": cls.feo.id, "name": "2019-01-01",
            "rate": 3.0, "company_id": cls.company.id,
        })

    def test_dos_retenciones_usd_no_arrastran_doble_redondeo(self):
        move = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1.0],
            taxes=self.iva_22, currency=self.feo)
        self.assertEqual(move.currency_id, self.feo)
        # Dos retenciones de 5% sobre base 1.0 -> 0.05 DBR cada una.
        for _i in range(2):
            self.env["qapps.retenciones.cce"].create({
                "move_id": move.id, "application_type": "retention",
                "base_calculation": "base", "percentage": 5.0,
            })
        self.assertEqual(
            set(move.retention_cce_ids.mapped("amount")), {0.05},
            "cada retención debe valer 0.05 DBR")

        comp = self.company.currency_id
        objetivo = self.feo._convert(0.10, comp, self.company, move.invoice_date or move.date)
        move.action_post()

        reclass = self.env["account.move"].search([
            ("ref", "=like", "Retenciones %"), ("move_type", "=", "entry"),
            ("partner_id", "=", move.partner_id.id),
            ("company_id", "=", move.company_id.id)], limit=1)
        self.assertTrue(reclass, "no se generó el asiento de reclasificación")

        ret_lines = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_retencion)
        # La suma en moneda compañía coincide con la conversión ÚNICA del total
        # (sin doble redondeo).
        self.assertAlmostEqual(
            sum(ret_lines.mapped("debit")), objetivo, places=2,
            msg="la suma de retenciones en moneda compañía arrastra doble redondeo")
        # amount_currency sigue exacto en moneda factura (0.10 DBR).
        self.assertAlmostEqual(
            sum(ret_lines.mapped("amount_currency")), 0.10, places=2,
            msg="el amount_currency total debe ser 0.10 DBR")
        # El asiento queda balanceado.
        self.assertAlmostEqual(
            sum(reclass.line_ids.mapped("debit")),
            sum(reclass.line_ids.mapped("credit")), places=2,
            msg="el asiento de reclasificación quedó descuadrado")

    def test_una_retencion_usd_sin_cambios(self):
        # Control: con una sola retención el reparto no altera nada (diff=0).
        move = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[1000.0],
            taxes=self.iva_22, currency=self.feo)
        self.env["qapps.retenciones.cce"].create({
            "move_id": move.id, "application_type": "retention",
            "base_calculation": "base", "percentage": 10.0,
        })
        comp = self.company.currency_id
        esperado = self.feo._convert(100.0, comp, self.company, move.invoice_date or move.date)
        move.action_post()
        reclass = self.env["account.move"].search([
            ("ref", "=like", "Retenciones %"), ("move_type", "=", "entry"),
            ("partner_id", "=", move.partner_id.id),
            ("company_id", "=", move.company_id.id)], limit=1)
        ret_lines = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_retencion)
        self.assertAlmostEqual(sum(ret_lines.mapped("debit")), esperado, places=2)
