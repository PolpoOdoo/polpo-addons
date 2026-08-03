from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QappsCheckEndorsement(models.Model):
    _name = "qapps.check.endorsement"
    _description = "Endoso de cheques a proveedor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "endorsement_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        readonly=True,
        default=lambda self: _("Nuevo"),
        copy=False,
        help="Número de endoso, asignado por secuencia al guardar.",
    )
    endorsement_date = fields.Date(
        string="Fecha de endoso",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        copy=False,
        help="Fecha en que se endosan los cheques; es la fecha del asiento contable generado.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Proveedor",
        required=True,
        tracking=True,
        domain=[("supplier_rank", ">", 0)],
        check_company=True,
        help="Proveedor al que se entregan los cheques endosados como medio de pago.",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario de cheques",
        domain="[('company_id', 'parent_of', company_id), ('is_check_journal', '=', True)]",
        required=True,
        check_company=True,
        tracking=True,
        help="Diario de cheques en cartera del cual se toman los cheques a endosar.",
    )
    in_hand_check_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta de cheques en cartera",
        compute="_compute_in_hand_check_account_id",
        store=True,
        help="Cuenta de cheques en cartera del diario seleccionado; de ella salen "
        "los cheques al validar el endoso.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda",
        compute="_compute_currency_id",
        store=True,
        precompute=True,
        readonly=False,
        required=True,
        tracking=True,
        help="Moneda de los cheques del endoso; se propone la del diario seleccionado.",
    )
    state = fields.Selection(
        selection=[("draft", "Borrador"), ("done", "Validado")],
        string="Estado",
        default="draft",
        readonly=True,
        tracking=True,
        copy=False,
        help="Borrador: editable. Validado: asiento generado y cheques endosados al proveedor.",
    )
    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Asiento contable",
        readonly=True,
        copy=False,
        check_company=True,
        help="Asiento que descarga los cheques de la cuenta de cartera contra el proveedor.",
    )
    check_payment_ids = fields.One2many(
        comodel_name="account.move.line",
        inverse_name="check_endorsement_id",
        string="Cheques a endosar",
        help="Apuntes de cheques en cartera incluidos en este endoso.",
    )
    invoice_ids = fields.Many2many(
        comodel_name="account.move",
        string="Facturas a saldar",
        domain="[('move_type', '=', 'in_invoice'),"
        " ('state', '=', 'posted'),"
        " ('payment_state', 'in', ('not_paid', 'partial')),"
        " ('partner_id', 'child_of', partner_id),"
        " ('company_id', '=', company_id)]",
        help="Facturas pendientes del proveedor que se concilian con el endoso al validarlo.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    total_check_amount = fields.Monetary(
        string="Total cheques",
        compute="_compute_check_totals",
        store=True,
        currency_field="currency_id",
        tracking=True,
        help="Suma de los cheques incluidos en el endoso.",
    )
    total_invoice_amount = fields.Monetary(
        string="Total facturas seleccionadas",
        compute="_compute_total_invoice_amount",
        currency_field="currency_id",
        help="Suma adeudada de las facturas seleccionadas, para comparar contra el total de cheques.",
    )
    check_count = fields.Integer(
        string="Cantidad de cheques",
        compute="_compute_check_totals",
        store=True,
    )

    _sql_constraints = [
        (
            "name_company_unique",
            "unique(company_id, name)",
            "Ya existe un endoso con esta referencia en esta compañía.",
        )
    ]

    @api.depends("journal_id")
    def _compute_in_hand_check_account_id(self):
        for rec in self:
            account = rec.journal_id.inbound_payment_method_line_ids.filtered(
                lambda line: line.payment_method_id.code == "manual"
            ).payment_account_id
            rec.in_hand_check_account_id = account[:1]

    @api.depends("journal_id")
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.journal_id.currency_id or rec.company_id.currency_id

    @api.depends(
        "currency_id",
        "company_id",
        "check_payment_ids.debit",
        "check_payment_ids.amount_currency",
    )
    def _compute_check_totals(self):
        for rec in self:
            company_currency = rec.company_id.currency_id
            if rec.currency_id and rec.currency_id != company_currency:
                check_total = sum(rec.check_payment_ids.mapped("amount_currency"))
            else:
                check_total = sum(rec.check_payment_ids.mapped("debit"))
            rec.total_check_amount = (
                rec.currency_id.round(check_total) if rec.currency_id else check_total
            )
            rec.check_count = len(rec.check_payment_ids)

    @api.depends(
        "currency_id",
        "company_id",
        "invoice_ids.amount_residual",
        "invoice_ids.amount_residual_signed",
    )
    def _compute_total_invoice_amount(self):
        for rec in self:
            company_currency = rec.company_id.currency_id
            payable_lines = rec.invoice_ids.line_ids.filtered(
                lambda l: l.account_id.account_type == "liability_payable"
                and not l.reconciled
            )
            if rec.currency_id and rec.currency_id != company_currency:
                invoice_total = sum(
                    abs(amount)
                    for amount in payable_lines.mapped("amount_residual_currency")
                )
            else:
                invoice_total = sum(
                    abs(amount) for amount in payable_lines.mapped("amount_residual")
                )
            rec.total_invoice_amount = (
                rec.currency_id.round(invoice_total)
                if rec.currency_id
                else invoice_total
            )

    @api.onchange("partner_id", "currency_id")
    def _onchange_reset_invoices(self):
        self.invoice_ids = [(5, 0, 0)]

    @api.constrains("currency_id", "check_payment_ids")
    def _check_currency(self):
        for rec in self:
            for line in rec.check_payment_ids:
                if line.currency_id != rec.currency_id:
                    raise ValidationError(
                        _(
                            "El cheque '%(ref)s' está en moneda %(check_currency)s pero el "
                            "endoso está en moneda %(endorsement_currency)s.",
                            ref=line.numero_cheque or line.ref or line.name or "",
                            check_currency=line.currency_id.name,
                            endorsement_currency=rec.currency_id.name,
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("company_id"):
                self = self.with_company(vals["company_id"])
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "qapps.check.endorsement", vals.get("endorsement_date")
                ) or _("Nuevo")
        return super().create(vals_list)

    def unlink(self):
        for rec in self.filtered(lambda x: x.state == "done"):
            raise UserError(
                _(
                    "El endoso '%s' está validado; debe volverlo a borrador antes de eliminarlo."
                )
                % rec.display_name
            )
        return super().unlink()

    def _get_payable_account(self):
        self.ensure_one()
        if self.invoice_ids:
            payable_lines = self.invoice_ids.line_ids.filtered(
                lambda l: l.account_id.account_type == "liability_payable"
                and not l.reconciled
            )
            accounts = payable_lines.account_id
            if not accounts:
                raise UserError(
                    _("Las facturas seleccionadas no tienen saldo pendiente por pagar.")
                )
            if len(accounts) > 1:
                raise UserError(
                    _(
                        "Las facturas seleccionadas usan más de una cuenta a pagar. "
                        "Realice un endoso por cada cuenta a pagar."
                    )
                )
            return accounts
        # Pago a cuenta (sin factura): usar la cuenta a pagar del proveedor.
        account = self.partner_id.with_company(
            self.company_id
        ).property_account_payable_id
        if not account:
            raise UserError(
                _("El proveedor '%s' no tiene configurada una cuenta a pagar.")
                % self.partner_id.display_name
            )
        return account

    def _check_before_validate(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("El endoso ya fue validado."))
        if not self.check_payment_ids:
            raise UserError(_("Debe seleccionar al menos un cheque a endosar."))
        if not self.in_hand_check_account_id:
            raise UserError(
                _(
                    "El diario '%s' no tiene configurada la cuenta de cheques en cartera "
                    "(método de pago Manual entrante)."
                )
                % self.journal_id.display_name
            )
        accounts = self.check_payment_ids.account_id
        if len(accounts) > 1 or (
            accounts and accounts != self.in_hand_check_account_id
        ):
            raise UserError(
                _(
                    "Todos los cheques deben pertenecer a la cuenta de cheques en cartera del diario seleccionado."
                )
            )
        other_currency = self.invoice_ids.filtered(
            lambda inv: inv.currency_id != self.currency_id
        )
        if other_currency:
            raise UserError(
                _(
                    "Por ahora no se puede endosar cheques para pagar facturas en otra moneda.\n\n"
                    "El endoso está en %(cur)s y las siguientes facturas están en otra moneda: %(facs)s.\n\n"
                    "El endoso con cruce de monedas (cheque en una moneda y factura en otra) "
                    "estará disponible una vez que se definan los requisitos de tipo de cambio. "
                    "Mientras tanto, endose cheques en la misma moneda que las facturas.",
                    facs=", ".join(other_currency.mapped("name")),
                    cur=self.currency_id.name,
                )
            )

    def _prepare_move_vals(self):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        total_debit = sum(self.check_payment_ids.mapped("debit"))
        total_amount_currency = sum(self.check_payment_ids.mapped("amount_currency"))
        total_debit = company_currency.round(total_debit)
        total_amount_currency = self.currency_id.round(total_amount_currency)
        payable_account = self._get_payable_account()
        label = _("Endoso de cheques %s") % self.name

        return {
            "journal_id": self.journal_id.id,
            "date": self.endorsement_date,
            "ref": label,
            "company_id": self.company_id.id,
            "line_ids": [
                (
                    0,
                    0,
                    {
                        "name": label,
                        "account_id": self.in_hand_check_account_id.id,
                        "partner_id": False,
                        "debit": 0.0,
                        "credit": total_debit,
                        "currency_id": self.currency_id.id,
                        "amount_currency": -total_amount_currency,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "name": label,
                        "account_id": payable_account.id,
                        "partner_id": self.partner_id.id,
                        "debit": total_debit,
                        "credit": 0.0,
                        "currency_id": self.currency_id.id,
                        "amount_currency": total_amount_currency,
                    },
                ),
            ],
        }

    def action_validate(self):
        for rec in self:
            rec._check_before_validate()
            move = self.env["account.move"].create(rec._prepare_move_vals())
            move.action_post()

            # Sacar los cheques de la cartera: conciliar las líneas de cheque
            # contra el crédito a la cuenta de cheques en cartera.
            credit_line = move.line_ids.filtered(
                lambda l: l.account_id == rec.in_hand_check_account_id
            )
            (rec.check_payment_ids + credit_line).reconcile()

            # Saldar las facturas seleccionadas: conciliar el débito a proveedor
            # contra sus líneas a pagar. Si no hay facturas, el débito queda
            # abierto como pago a cuenta del proveedor (reconciliable luego).
            debit_line = move.line_ids.filtered(
                lambda l: l.account_id != rec.in_hand_check_account_id
            )
            if rec.invoice_ids:
                invoice_payable_lines = rec.invoice_ids.line_ids.filtered(
                    lambda l: l.account_id == debit_line.account_id and not l.reconciled
                )
                (debit_line + invoice_payable_lines).reconcile()

            rec.message_post(
                body=_(
                    "Endoso validado: %(count)s cheques entregados a %(partner)s%(mode)s."
                )
                % {
                    "count": len(rec.check_payment_ids),
                    "partner": rec.partner_id.display_name,
                    "mode": "" if rec.invoice_ids else _(" (pago a cuenta)"),
                }
            )
            rec.write({"state": "done", "move_id": move.id})
        return True

    def action_back_to_draft(self):
        for rec in self:
            if rec.move_id:
                move = rec.move_id
                move.line_ids.remove_move_reconcile()
                if move.state == "posted":
                    move.button_cancel()
                move.with_context(force_delete=True).unlink()
            rec.write({"state": "draft"})
        return True

    def action_open_move(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento contable"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }
