# -*- coding: utf-8 -*-
"""Regresión / cobertura — circuito de ENDOSO de cheque en MONEDA EXTRANJERA.

El endoso a proveedor (qapps.check.endorsement.action_validate) arma a mano un
asiento y reconcilia el cheque + (opcional) las facturas. No tenía cobertura para
moneda extranjera. EI opera dual-currency UYU/USD, así que el endoso de un cheque
en USD debe: quedar en la moneda del cheque, generar un asiento BALANCEADO con
currency_id/amount_currency correctos, sacar el cheque de la cartera (reconciliar
la línea de cartera) y dejar el débito a proveedor como pago a cuenta.

Replica el flujo REAL de la cartera (action_create_endorsement -> crear desde el
contexto -> validar).
"""
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestEndosoUsd(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a
        cls.partner.supplier_rank = 1  # habilita el dominio de proveedor del endoso
        cls.foreign = cls.currency_data["currency"]  # moneda extranjera con tasa
        cls.Wallet = cls.env["qapps.check.wallet"]

    @classmethod
    def _diario_cheques(cls):
        cuenta = cls.env["account.account"].create({
            "name": "Cheques cartera USD", "code": "CHQUSD",
            "account_type": "asset_current", "company_id": cls.company.id})
        diario = cls.env["account.journal"].create({
            "name": "Cheques USD", "type": "bank", "code": "CHKD",
            "company_id": cls.company.id, "is_check_journal": True})
        diario.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == "manual"
        ).payment_account_id = cuenta.id
        cls.env.flush_all()
        return diario, cuenta

    def _cheque_usd_en_cartera(self, diario, cuenta, amount_fc=100.0):
        """Cheque recibido en moneda extranjera: amount_currency=amount_fc."""
        contra = self.company_data["default_account_receivable"]
        debit_comp = self.foreign._convert(
            amount_fc, self.company.currency_id, self.company, "2020-06-10")
        move = self.env["account.move"].create({
            "journal_id": diario.id, "date": "2020-06-10",
            "line_ids": [
                (0, 0, {"name": "Chq USD", "account_id": cuenta.id,
                        "partner_id": self.partner.id,
                        "debit": debit_comp, "credit": 0.0,
                        "currency_id": self.foreign.id, "amount_currency": amount_fc,
                        "numero_cheque": "USD0001"}),
                (0, 0, {"name": "c", "account_id": contra.id,
                        "partner_id": self.partner.id,
                        "debit": 0.0, "credit": debit_comp,
                        "currency_id": self.foreign.id, "amount_currency": -amount_fc}),
            ]})
        move.action_post()
        self.env.flush_all()
        return move.line_ids.filtered(lambda l: l.account_id == cuenta)

    def test_endoso_usd_pago_a_cuenta_circuito_completo(self):
        diario, cuenta = self._diario_cheques()
        linea = self._cheque_usd_en_cartera(diario, cuenta, amount_fc=100.0)
        registro = self.Wallet.search([("move_line_id", "=", linea.id)])
        self.assertEqual(registro.currency_id, self.foreign,
            "el cheque en cartera debe figurar en USD")

        # Flujo real: la cartera arma el contexto del endoso.
        accion = registro.action_create_endorsement()
        ctx = accion["context"]
        self.assertEqual(ctx["default_currency_id"], self.foreign.id,
            "la cartera debe precargar la moneda del cheque (USD), no la compañía")

        endoso = self.env["qapps.check.endorsement"].create({
            "journal_id": ctx["default_journal_id"],
            "currency_id": ctx["default_currency_id"],
            "check_payment_ids": ctx["default_check_payment_ids"],
            "partner_id": self.partner.id,  # pago a cuenta (sin facturas)
        })
        self.assertEqual(endoso.currency_id, self.foreign)
        self.assertAlmostEqual(endoso.total_check_amount, 100.0, places=2,
            msg="el total del endoso debe leerse en USD (amount_currency)")

        endoso.action_validate()
        self.assertEqual(endoso.state, "done")

        move = endoso.move_id
        self.assertTrue(move and move.state == "posted")
        # Asiento balanceado.
        self.assertAlmostEqual(
            sum(move.line_ids.mapped("debit")),
            sum(move.line_ids.mapped("credit")), places=2,
            msg="el asiento de endoso quedó descuadrado")
        # Ambas líneas en USD con amount_currency.
        for l in move.line_ids:
            self.assertEqual(l.currency_id, self.foreign,
                "las líneas del endoso deben llevar la moneda del cheque (USD)")
        self.assertAlmostEqual(
            sum(abs(a) for a in move.line_ids.mapped("amount_currency")) / 2.0,
            100.0, places=2,
            msg="el amount_currency del endoso no refleja 100 USD")
        # El cheque salió de la cartera: su línea quedó conciliada.
        self.assertTrue(linea.reconciled,
            "la línea de cheque en cartera debe quedar conciliada tras el endoso")
        # La línea quedó enganchada al endoso (FK que la VIEW SQL lee para el estado).
        self.assertEqual(linea.check_endorsement_id, endoso,
            "la línea de cheque debe quedar enganchada al endoso")
        # Ya no figura como pendiente en la cartera. La cartera es una VIEW SQL
        # (_auto=False): hay que bajar los cambios a Postgres (flush) e invalidar
        # la caché del ORM (la VIEW se leyó antes del endoso con estado 'pending'
        # y el ORM no sabe que el SQL subyacente cambió) antes de reconsultarla.
        self.env.flush_all()
        self.env.invalidate_all()
        registro2 = self.Wallet.search([("move_line_id", "=", linea.id)])
        self.assertEqual(registro2.state, "endorsed")
