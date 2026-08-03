# -*- coding: utf-8 -*-
"""Tests del cron de notificación de vencimientos (_cron_notify_due_checks).

El bug que cubren: ``message_notify`` (igual que ``message_post``) hace
``escape(body)`` — solo respeta el HTML si el body es un ``markupsafe.Markup``.
Con un ``str`` plano el usuario ve las etiquetas ``<p>``/``<ul>``/``<li>``
literales en Conversaciones. Además, los datos interpolados (nombre del
partner) sí deben escaparse.
"""
from odoo import fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestNotifyDueChecks(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Wallet = cls.env["qapps.check.wallet"]
        # Un solo destinatario controlado: el cron notifica a los usuarios del
        # grupo de facturación con acceso a la compañía del cheque.
        cls.grupo = cls.env.ref("account.group_account_invoice")
        cls.usuario = cls.env["res.users"].create({
            "name": "Contadora cheques",
            "login": "cheques_cron_test",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, cls.company.ids)],
            "groups_id": [(6, 0, cls.grupo.ids)],
        })
        # Nombre con HTML: debe llegar escapado al cuerpo del mensaje.
        cls.partner = cls.env["res.partner"].create({
            "name": "Cliente <b>riesgoso</b>",
        })

    @classmethod
    def _crear_diario_cheques(cls):
        cuenta_cartera = cls.env["account.account"].create({
            "name": "Cheques en cartera",
            "code": "CHQNOT",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        diario = cls.env["account.journal"].create({
            "name": "Cheques recibidos (cron)",
            "type": "bank",
            "code": "CHNT",
            "company_id": cls.company.id,
            "is_check_journal": True,
        })
        linea_manual = diario.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == "manual"
        )
        linea_manual.payment_account_id = cuenta_cartera.id
        # La cartera es una VIEW SQL (_auto=False): bajar a Postgres antes de
        # consultarla.
        cls.env.flush_all()
        return diario, cuenta_cartera

    def _asentar_cheque_que_vence_hoy(self, diario, cuenta_cartera):
        hoy = fields.Date.context_today(self.env.user)
        contrapartida = self.company_data["default_account_receivable"]
        move = self.env["account.move"].create({
            "journal_id": diario.id,
            "date": hoy,
            "line_ids": [
                (0, 0, {
                    "name": "Cheque cliente",
                    "account_id": cuenta_cartera.id,
                    "partner_id": self.partner.id,
                    "debit": 1000.0,
                    "credit": 0.0,
                    "numero_cheque": "00099887",
                    "vencimiento": hoy,
                }),
                (0, 0, {
                    "name": "Contrapartida",
                    "account_id": contrapartida.id,
                    "partner_id": self.partner.id,
                    "debit": 0.0,
                    "credit": 1000.0,
                }),
            ],
        })
        move.action_post()
        self.env.flush_all()
        return move

    def _mensajes_del_cron(self):
        return self.env["mail.message"].search([
            ("partner_ids", "in", self.usuario.partner_id.ids),
            ("subject", "like", "Cheques: vencimientos del día"),
        ])

    # ------------------------------------------------------------------ #
    #  Cuerpo del mensaje                                                 #
    # ------------------------------------------------------------------ #
    def test_body_es_html_no_texto_escapado(self):
        diario, cuenta = self._crear_diario_cheques()
        self._asentar_cheque_que_vence_hoy(diario, cuenta)

        self.Wallet._cron_notify_due_checks()

        mensajes = self._mensajes_del_cron()
        self.assertEqual(
            len(mensajes), 1, "El cron debe notificar una vez al usuario."
        )
        body = mensajes.body
        self.assertIn("<li>", body, "El HTML del detalle debe llegar como HTML.")
        self.assertIn("<ul>", body)
        self.assertNotIn(
            "&lt;li&gt;",
            body,
            "El body no debe llegar escapado: message_notify hace escape() "
            "si no recibe un Markup.",
        )
        self.assertIn("00099887", body)

    def test_datos_del_partner_se_escapan(self):
        """El template va como Markup, pero los valores interpolados no: un
        nombre de partner con HTML no debe inyectarse en el mensaje."""
        diario, cuenta = self._crear_diario_cheques()
        self._asentar_cheque_que_vence_hoy(diario, cuenta)

        self.Wallet._cron_notify_due_checks()

        body = self._mensajes_del_cron().body
        self.assertIn("Cliente &lt;b&gt;riesgoso&lt;/b&gt;", body)
        self.assertNotIn("<b>riesgoso</b>", body)

    def test_sin_cheques_no_notifica(self):
        self.Wallet._cron_notify_due_checks()
        self.assertFalse(self._mensajes_del_cron())
