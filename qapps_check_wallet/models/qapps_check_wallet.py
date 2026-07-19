from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools import format_date, formatLang


class QappsCheckWallet(models.Model):
    _name = "qapps.check.wallet"
    _description = "Cheques en cartera"
    _auto = False
    _order = "due_date asc, payment_date asc"
    _rec_name = "check_number"

    move_line_id = fields.Many2one(
        "account.move.line", string="Apunte contable", readonly=True
    )
    payment_id = fields.Many2one(
        "account.payment",
        string="Pago",
        readonly=True,
        help="Pago de cliente con el que se recibió el cheque.",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Asiento contable",
        readonly=True,
        help="Asiento del pago que contiene el apunte del cheque en cartera.",
    )

    payment_date = fields.Date(
        string="Fecha del pago",
        readonly=True,
        help="Fecha del pago con el que se recibió el cheque.",
    )
    due_date = fields.Date(
        string="Vencimiento",
        readonly=True,
        help="Fecha de vencimiento del cheque diferido. Ordena la cartera y "
        "dispara la notificación diaria de vencimientos.",
    )
    check_number = fields.Char(string="Número de cheque", readonly=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario",
        readonly=True,
        help="Diario de cheques en cartera donde está contabilizado el cheque.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        readonly=True,
        help="Cliente que entregó el cheque.",
    )
    bank_reference = fields.Char(
        string="Referencia / Banco",
        readonly=True,
        help="Referencia del cheque: banco emisor u observaciones del pago.",
    )
    currency_id = fields.Many2one("res.currency", string="Moneda", readonly=True)
    amount = fields.Monetary(
        string="Importe", readonly=True, currency_field="currency_id"
    )
    amount_company = fields.Monetary(
        string="Importe en moneda compañía",
        readonly=True,
        currency_field="company_currency_id",
    )
    company_currency_id = fields.Many2one(
        "res.currency", string="Moneda compañía", readonly=True
    )

    check_deposit_id = fields.Many2one(
        "account.check.deposit",
        string="Boleta de depósito",
        readonly=True,
        help="Boleta de depósito (account_check_deposit) que incluye este cheque.",
    )
    deposit_state = fields.Selection(
        selection=[("draft", "Borrador"), ("done", "Validada")],
        string="Estado boleta",
        readonly=True,
        help="Estado de la boleta de depósito que incluye el cheque.",
    )
    check_endorsement_id = fields.Many2one(
        "qapps.check.endorsement",
        string="Endoso",
        readonly=True,
        help="Endoso a proveedor que incluye este cheque.",
    )
    endorsement_state = fields.Selection(
        selection=[("draft", "Borrador"), ("done", "Validado")],
        string="Estado endoso",
        readonly=True,
        help="Estado del endoso que incluye el cheque.",
    )
    check_collection_id = fields.Many2one(
        "qapps.check.collection",
        string="Envío al cobro",
        readonly=True,
        help="Envío al cobro (entrega al banco) que incluye este cheque.",
    )
    collection_doc_state = fields.Selection(
        selection=[("draft", "Borrador"), ("sent", "Enviado al cobro")],
        string="Estado envío",
        readonly=True,
        help="Estado del documento de envío al cobro que incluye el cheque.",
    )
    collection_settle_move_id = fields.Many2one(
        "account.move",
        string="Asiento de acreditación / rechazo",
        readonly=True,
        help="Asiento generado al acreditar o rechazar el cheque enviado al cobro.",
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pendiente"),
            ("in_deposit", "En boleta"),
            ("deposited", "Depositado"),
            ("in_endorsement", "En endoso"),
            ("endorsed", "Endosado"),
            ("in_collection", "En envío al cobro"),
            ("at_collection", "Al cobro"),
            ("credited", "Acreditado"),
            ("rejected", "Rechazado"),
        ],
        string="Estado",
        readonly=True,
        help="Ciclo de vida del cheque: Pendiente (en cartera), En boleta / Depositado, "
        "En endoso / Endosado, En envío / Al cobro, y Acreditado o Rechazado según "
        "lo que resuelva el banco.",
    )
    company_id = fields.Many2one("res.company", string="Compañía", readonly=True)

    def action_open_payment(self):
        self.ensure_one()
        if not self.payment_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Pago"),
            "res_model": "account.payment",
            "res_id": self.payment_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento contable"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_deposit(self):
        self.ensure_one()
        if not self.check_deposit_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Boleta de depósito"),
            "res_model": "account.check.deposit",
            "res_id": self.check_deposit_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_endorsement(self):
        self.ensure_one()
        if not self.check_endorsement_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Endoso de cheques"),
            "res_model": "qapps.check.endorsement",
            "res_id": self.check_endorsement_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_endorsement(self):
        """Abre un endoso en borrador con los cheques pendientes seleccionados
        precargados. El proveedor a quien se endosa (partner_id, required) lo
        elige el usuario en el formulario antes de guardar."""
        checks = self.filtered(lambda r: r.state == "pending")
        if not checks:
            raise UserError(
                _("Seleccione cheques pendientes (no depositados ni ya endosados).")
            )
        move_lines = checks.mapped("move_line_id")
        if len(move_lines.account_id) > 1:
            raise UserError(
                _(
                    "Todos los cheques seleccionados deben estar en la misma cuenta de cheques en cartera."
                )
            )
        if len(move_lines.currency_id) > 1:
            raise UserError(
                _("Todos los cheques seleccionados deben estar en la misma moneda.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Endoso de cheques"),
            "res_model": "qapps.check.endorsement",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
            "context": {
                "default_journal_id": move_lines.journal_id[:1].id,
                "default_currency_id": move_lines.currency_id[:1].id
                or self.env.company.currency_id.id,
                "default_check_payment_ids": [(6, 0, move_lines.ids)],
            },
        }

    def action_open_collection(self):
        self.ensure_one()
        if not self.check_collection_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Envío al cobro"),
            "res_model": "qapps.check.collection",
            "res_id": self.check_collection_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_settle_move(self):
        self.ensure_one()
        if not self.collection_settle_move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento de acreditación / rechazo"),
            "res_model": "account.move",
            "res_id": self.collection_settle_move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_create_collection(self):
        """Abre un envío al cobro en borrador con los cheques pendientes
        seleccionados precargados. El banco destino (bank_journal_id, required)
        lo elige el usuario en el formulario antes de guardar."""
        checks = self.filtered(lambda r: r.state == "pending")
        if not checks:
            raise UserError(
                _(
                    "Seleccione cheques pendientes (no depositados, endosados ni ya enviados al cobro)."
                )
            )
        move_lines = checks.mapped("move_line_id")
        if len(move_lines.account_id) > 1:
            raise UserError(
                _(
                    "Todos los cheques seleccionados deben estar en la misma cuenta de cheques en cartera."
                )
            )
        if len(move_lines.currency_id) > 1:
            raise UserError(
                _("Todos los cheques seleccionados deben estar en la misma moneda.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Envío al cobro"),
            "res_model": "qapps.check.collection",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
            "context": {
                "default_journal_id": move_lines.journal_id[:1].id,
                "default_currency_id": move_lines.currency_id[:1].id
                or self.env.company.currency_id.id,
                "default_check_payment_ids": [(6, 0, move_lines.ids)],
            },
        }

    def action_credit_collection(self):
        """Acredita en banco los cheques al cobro seleccionados."""
        checks = self.filtered(lambda r: r.state == "at_collection")
        if not checks:
            raise UserError(_('Seleccione cheques en estado "Al cobro".'))
        self.env["qapps.check.collection"]._process_checks(
            checks.mapped("move_line_id"), "credit"
        )
        return True

    def action_reject_collection(self):
        """Registra el rechazo de los cheques al cobro seleccionados."""
        checks = self.filtered(lambda r: r.state == "at_collection")
        if not checks:
            raise UserError(_('Seleccione cheques en estado "Al cobro".'))
        self.env["qapps.check.collection"]._process_checks(
            checks.mapped("move_line_id"), "reject"
        )
        return True

    @api.model
    def get_dashboard_totals(self):
        today = fields.Date.context_today(self)
        company_currency = self.env.company.currency_id

        def _totals(domain):
            res = self.read_group(domain, ["amount_company:sum"], [])
            return {
                "amount": res[0]["amount_company"] if res else 0.0,
                "count": res[0]["__count"] if res else 0,
            }

        pending = _totals([("state", "=", "pending")])
        deposited = _totals([("state", "=", "deposited")])
        at_collection = _totals([("state", "=", "at_collection")])
        overdue = _totals(
            [
                ("state", "=", "pending"),
                ("due_date", "!=", False),
                ("due_date", "<", today),
            ]
        )

        return {
            "pending_amount": pending["amount"],
            "pending_count": pending["count"],
            "deposited_amount": deposited["amount"],
            "deposited_count": deposited["count"],
            "at_collection_amount": at_collection["amount"],
            "at_collection_count": at_collection["count"],
            "overdue_amount": overdue["amount"],
            "overdue_count": overdue["count"],
            "total_count": self.search_count([]),
            "currency_id": company_currency.id,
        }

    @api.model
    def _cron_notify_due_checks(self):
        """Notifica una vez al día a los usuarios con acceso a Facturación:
        - los cheques en cartera que vencen en el día (para depositar/transferir);
        - los cheques al cobro vencidos o que vencen hoy (para que el usuario
          confirme la acreditación bancaria o registre el rechazo)."""
        today = fields.Date.context_today(self)
        due_checks = self.search([("state", "=", "pending"), ("due_date", "=", today)])
        collection_checks = self.search(
            [
                ("state", "=", "at_collection"),
                ("due_date", "!=", False),
                ("due_date", "<=", today),
            ]
        )
        if not due_checks and not collection_checks:
            return
        group = self.env.ref("account.group_account_invoice", raise_if_not_found=False)
        if not group:
            return
        users = group.users.filtered(
            lambda u: u.active and not u.share and u.partner_id
        )
        if not users:
            return

        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        action = self.env.ref(
            "qapps_check_wallet.qapps_check_wallet_action", raise_if_not_found=False
        )
        action_part = ("&action=%s" % action.id) if action else ""
        date_str = format_date(self.env, today)

        def _rows(checks):
            rows = []
            for check in checks:
                url = "%s/web#id=%s&model=qapps.check.wallet&view_type=form%s" % (
                    base_url or "",
                    check.id,
                    action_part,
                )
                amount_txt = formatLang(
                    self.env, check.amount, currency_obj=check.currency_id
                )
                rows.append(
                    '<li>Cheque <strong>%s</strong> — %s — %s — <a href="%s">Ver cheque</a></li>'
                    % (
                        check.check_number or _("s/n"),
                        check.partner_id.display_name or "",
                        amount_txt,
                        url,
                    )
                )
            return "".join(rows)

        for user in users:
            user_due = due_checks.filtered(lambda c: c.company_id in user.company_ids)
            user_collection = collection_checks.filtered(
                lambda c: c.company_id in user.company_ids
            )
            if not user_due and not user_collection:
                continue
            body = ""
            if user_due:
                body += _(
                    "<p>Cheques en cartera que vencen hoy (%(date)s):</p>"
                    "<ul>%(rows)s</ul>"
                    "<p>Recordá realizar el depósito o la transferencia correspondiente.</p>",
                    date=date_str,
                    rows=_rows(user_due),
                )
            if user_collection:
                body += _(
                    "<p>Cheques al cobro vencidos o que vencen hoy (%(date)s):</p>"
                    "<ul>%(rows)s</ul>"
                    "<p>Confirmá la acreditación bancaria o registrá el rechazo según corresponda.</p>",
                    date=date_str,
                    rows=_rows(user_collection),
                )
            self.env["mail.thread"].message_notify(
                partner_ids=user.partner_id.ids,
                subject=_("Cheques: vencimientos del día (%s)") % date_str,
                body=body,
            )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    aml.id AS id,
                    aml.id AS move_line_id,
                    am.payment_id AS payment_id,
                    aml.move_id AS move_id,
                    aml.date AS payment_date,
                    COALESCE(aml.vencimiento, aml.date_maturity) AS due_date,
                    aml.numero_cheque AS check_number,
                    aml.journal_id AS journal_id,
                    aml.partner_id AS partner_id,
                    aml.ref AS bank_reference,
                    aml.currency_id AS currency_id,
                    CASE
                        WHEN aml.currency_id IS NOT NULL AND aml.currency_id != comp.currency_id
                            THEN aml.amount_currency
                        ELSE aml.debit
                    END AS amount,
                    aml.debit AS amount_company,
                    comp.currency_id AS company_currency_id,
                    aml.check_deposit_id AS check_deposit_id,
                    dep.state AS deposit_state,
                    aml.check_endorsement_id AS check_endorsement_id,
                    endo.state AS endorsement_state,
                    aml.check_collection_id AS check_collection_id,
                    coll.state AS collection_doc_state,
                    aml.collection_settle_move_id AS collection_settle_move_id,
                    CASE
                        WHEN aml.check_deposit_id IS NOT NULL AND dep.state = 'done' THEN 'deposited'
                        WHEN aml.check_endorsement_id IS NOT NULL AND endo.state = 'done' THEN 'endorsed'
                        WHEN aml.check_collection_state = 'credited' THEN 'credited'
                        WHEN aml.check_collection_state = 'rejected' THEN 'rejected'
                        WHEN aml.check_collection_state = 'at_collection' THEN 'at_collection'
                        WHEN aml.check_deposit_id IS NOT NULL THEN 'in_deposit'
                        WHEN aml.check_endorsement_id IS NOT NULL THEN 'in_endorsement'
                        WHEN aml.check_collection_id IS NOT NULL THEN 'in_collection'
                        ELSE 'pending'
                    END AS state,
                    aml.company_id AS company_id
                FROM account_move_line aml
                INNER JOIN account_move am ON am.id = aml.move_id
                INNER JOIN res_company comp ON comp.id = aml.company_id
                LEFT JOIN account_check_deposit dep ON dep.id = aml.check_deposit_id
                LEFT JOIN qapps_check_endorsement endo ON endo.id = aml.check_endorsement_id
                LEFT JOIN qapps_check_collection coll ON coll.id = aml.check_collection_id
                WHERE aml.parent_state = 'posted'
                  AND aml.debit > 0
                  AND aml.account_id IN (
                      SELECT pml.payment_account_id
                      FROM account_payment_method_line pml
                      INNER JOIN account_payment_method pm ON pm.id = pml.payment_method_id
                      INNER JOIN account_journal j ON j.id = pml.journal_id
                      WHERE pml.payment_account_id IS NOT NULL
                        AND pm.code = 'manual'
                        AND pm.payment_type = 'inbound'
                        AND j.is_check_journal = TRUE
                  )
            )
        """)
