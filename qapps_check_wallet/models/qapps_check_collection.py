from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QappsCheckCollection(models.Model):
    """Envío de cheques en cartera al banco 'al cobro'.

    Documento que agrupa los cheques entregados al banco antes del vencimiento.
    Al validar (enviar al cobro) mueve el importe desde la cuenta de cheques en
    cartera hacia una cuenta puente por moneda. La acreditación o el rechazo se
    resuelven por cheque individual desde la lista 'Al cobro', ya que un mismo
    envío puede acreditar varios cheques y que otro sea rechazado."""

    _name = "qapps.check.collection"
    _description = "Cheques enviados al banco al cobro"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "collection_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        readonly=True,
        default=lambda self: _("Nuevo"),
        copy=False,
        help="Número de envío al cobro, asignado por secuencia al guardar.",
    )
    collection_date = fields.Date(
        string="Fecha de envío",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        copy=False,
        help="Fecha en que se entregan los cheques al banco; es la fecha del asiento de envío.",
    )
    boleta_ref = fields.Char(
        string="Referencia de boleta",
        tracking=True,
        copy=False,
        help="Número de la boleta bancaria presentada. Una misma boleta puede "
        "agrupar cheques de la casa central y de la sucursal: se registran dos "
        "envíos (uno por compañía) con la misma referencia para relacionarlos. "
        "Editable también con el envío validado, porque el número de boleta "
        "puede conocerse después de enviar los cheques.",
    )
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Diario de cheques",
        domain="[('company_id', 'parent_of', company_id), ('is_check_journal', '=', True)]",
        required=True,
        check_company=True,
        tracking=True,
        help="Diario de cheques en cartera del cual se toman los cheques a enviar.",
    )
    bank_journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Banco destino",
        domain="[('company_id', 'parent_of', company_id), ('type', '=', 'bank'),"
        " ('bank_account_id', '!=', False)]",
        required=True,
        check_company=True,
        tracking=True,
        help="Banco al que se entregan los cheques al cobro y que los acreditará al vencimiento.",
    )
    in_hand_check_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta de cheques en cartera",
        compute="_compute_in_hand_check_account_id",
        store=True,
        help="Cuenta de cheques en cartera del diario seleccionado; de ella salen "
        "los cheques al validar el envío.",
    )
    collection_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta cheques al cobro",
        compute="_compute_collection_accounts",
        help="Cuenta puente por moneda (configurada en Cheques al cobro: cuentas).",
    )
    rejected_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta cheques rechazados",
        compute="_compute_collection_accounts",
        help="Cuenta de cheques rechazados por moneda (configurada en Cheques al cobro: cuentas).",
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
        help="Moneda de los cheques del envío; se propone la del diario seleccionado.",
    )
    state = fields.Selection(
        selection=[("draft", "Borrador"), ("sent", "Enviado al cobro")],
        string="Estado",
        default="draft",
        readonly=True,
        tracking=True,
        copy=False,
        help="Borrador: editable. Enviado al cobro: asiento generado; la acreditación "
        "o el rechazo se resuelven por cheque individual desde la cartera.",
    )
    move_id = fields.Many2one(
        comodel_name="account.move",
        string="Asiento de envío",
        readonly=True,
        copy=False,
        check_company=True,
        help='Asiento que mueve los cheques de la cuenta de cartera a la cuenta puente "al cobro".',
    )
    check_payment_ids = fields.One2many(
        comodel_name="account.move.line",
        inverse_name="check_collection_id",
        string="Cheques a enviar",
        help="Apuntes de cheques en cartera incluidos en este envío al cobro.",
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
        help="Suma de los cheques incluidos en el envío.",
    )
    check_count = fields.Integer(
        string="Cantidad de cheques",
        compute="_compute_check_totals",
        store=True,
    )
    credited_count = fields.Integer(
        string="Acreditados",
        compute="_compute_check_totals",
        store=True,
        help="Cheques de este envío que el banco ya acreditó.",
    )
    rejected_count = fields.Integer(
        string="Rechazados",
        compute="_compute_check_totals",
        store=True,
        help="Cheques de este envío que el banco rechazó.",
    )

    _sql_constraints = [
        (
            "name_company_unique",
            "unique(company_id, name)",
            "Ya existe un envío al cobro con esta referencia en esta compañía.",
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

    @api.depends("company_id", "currency_id")
    def _compute_collection_accounts(self):
        mapping_model = self.env["qapps.check.collection.account"]
        for rec in self:
            mapping = mapping_model._find_mapping(rec.company_id, rec.currency_id)
            rec.collection_account_id = mapping.collection_account_id
            rec.rejected_account_id = mapping.rejected_account_id

    @api.depends(
        "currency_id",
        "company_id",
        "check_payment_ids.debit",
        "check_payment_ids.amount_currency",
        "check_payment_ids.check_collection_state",
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
            rec.credited_count = len(
                rec.check_payment_ids.filtered(
                    lambda l: l.check_collection_state == "credited"
                )
            )
            rec.rejected_count = len(
                rec.check_payment_ids.filtered(
                    lambda l: l.check_collection_state == "rejected"
                )
            )

    @api.constrains("currency_id", "check_payment_ids")
    def _check_currency(self):
        for rec in self:
            for line in rec.check_payment_ids:
                if line.currency_id != rec.currency_id:
                    raise ValidationError(
                        _(
                            "El cheque '%(ref)s' está en moneda %(check_currency)s pero el "
                            "envío al cobro está en moneda %(collection_currency)s.",
                            ref=line.numero_cheque or line.ref or line.name or "",
                            check_currency=line.currency_id.name,
                            collection_currency=rec.currency_id.name,
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("company_id"):
                self = self.with_company(vals["company_id"])
            if vals.get("name", _("Nuevo")) == _("Nuevo"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "qapps.check.collection", vals.get("collection_date")
                ) or _("Nuevo")
        return super().create(vals_list)

    def unlink(self):
        for rec in self.filtered(lambda x: x.state == "sent"):
            raise UserError(
                _(
                    "El envío al cobro '%s' está validado; debe volverlo a borrador "
                    "antes de eliminarlo."
                )
                % rec.display_name
            )
        return super().unlink()

    # ------------------------------------------------------------------
    # Validación / envío al cobro
    # ------------------------------------------------------------------
    def _check_before_validate(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("El envío al cobro ya fue validado."))
        if not self.check_payment_ids:
            raise UserError(_("Debe seleccionar al menos un cheque a enviar al cobro."))
        if not self.in_hand_check_account_id:
            raise UserError(
                _(
                    "El diario '%s' no tiene configurada la cuenta de cheques en cartera "
                    "(método de pago Manual entrante)."
                )
                % self.journal_id.display_name
            )
        if not self.collection_account_id:
            raise UserError(
                _(
                    "No hay cuenta de cheques al cobro configurada para la moneda '%(currency)s'.\n\n"
                    "Configúrela en Contabilidad > Configuración > Cheques al cobro: cuentas.",
                    currency=self.currency_id.display_name,
                )
            )
        accounts = self.check_payment_ids.account_id
        if len(accounts) > 1 or (
            accounts and accounts != self.in_hand_check_account_id
        ):
            raise UserError(
                _(
                    "Todos los cheques deben pertenecer a la cuenta de cheques en cartera "
                    "del diario seleccionado."
                )
            )

    def _prepare_send_move_vals(self):
        self.ensure_one()
        label = _("Envío al cobro %s") % self.name
        line_vals = []
        for check in self.check_payment_ids:
            ref = check.numero_cheque or check.ref or label
            # Sale de cartera (haber) ...
            line_vals.append(
                (
                    0,
                    0,
                    {
                        "name": ref,
                        "account_id": self.in_hand_check_account_id.id,
                        "partner_id": check.partner_id.id,
                        "debit": 0.0,
                        "credit": check.debit,
                        "currency_id": check.currency_id.id,
                        "amount_currency": -check.amount_currency,
                        "collection_check_line_id": check.id,
                    },
                )
            )
            # ... y entra a la cuenta puente al cobro (debe).
            line_vals.append(
                (
                    0,
                    0,
                    {
                        "name": ref,
                        "account_id": self.collection_account_id.id,
                        "partner_id": check.partner_id.id,
                        "debit": check.debit,
                        "credit": 0.0,
                        "currency_id": check.currency_id.id,
                        "amount_currency": check.amount_currency,
                        "collection_check_line_id": check.id,
                    },
                )
            )
        return {
            "journal_id": self.journal_id.id,
            "date": self.collection_date,
            "ref": label,
            "company_id": self.company_id.id,
            "line_ids": line_vals,
        }

    def action_validate(self):
        for rec in self:
            rec._check_before_validate()
            move = self.env["account.move"].create(rec._prepare_send_move_vals())
            move.action_post()

            # Sacar los cheques de la cartera: conciliar las líneas de cheque
            # originales contra los créditos a la cuenta de cheques en cartera.
            wallet_lines = move.line_ids.filtered(
                lambda l: l.account_id == rec.in_hand_check_account_id
            )
            (rec.check_payment_ids + wallet_lines).reconcile()

            rec.check_payment_ids.write({"check_collection_state": "at_collection"})
            rec.message_post(
                body=_("Cheques enviados al cobro: %(count)s entregados a %(bank)s.")
                % {
                    "count": len(rec.check_payment_ids),
                    "bank": rec.bank_journal_id.display_name,
                }
            )
            rec.write({"state": "sent", "move_id": move.id})
        return True

    def action_back_to_draft(self):
        for rec in self:
            settled = rec.check_payment_ids.filtered(
                lambda l: l.check_collection_state in ("credited", "rejected")
            )
            if settled:
                raise UserError(
                    _(
                        "No se puede volver a borrador: hay cheques ya acreditados o "
                        "rechazados en este envío. Revierta primero esos movimientos."
                    )
                )
            if rec.move_id:
                move = rec.move_id
                move.line_ids.remove_move_reconcile()
                if move.state == "posted":
                    move.button_cancel()
                move.with_context(force_delete=True).unlink()
            rec.check_payment_ids.write({"check_collection_state": False})
            rec.write({"state": "draft", "move_id": False})
        return True

    def action_open_move(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Asiento de envío"),
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    # ------------------------------------------------------------------
    # Acreditación / rechazo por cheque (invocado desde la cartera)
    # ------------------------------------------------------------------
    def _get_bridge_line(self, check):
        """Línea abierta en la cuenta puente correspondiente a un cheque."""
        return self.env["account.move.line"].search(
            [
                ("collection_check_line_id", "=", check.id),
                ("account_id", "=", self.collection_account_id.id),
                ("reconciled", "=", False),
                ("parent_state", "=", "posted"),
            ],
            limit=1,
        )

    @api.model
    def _process_checks(self, check_lines, operation, date=None):
        """Acredita ('credit') o rechaza ('reject') una selección de cheques al
        cobro. Agrupa por envío (para tomar banco/moneda/cuentas) y genera un
        asiento por cheque, conciliando su línea de puente."""
        date = date or fields.Date.context_today(self)
        amlo = self.env["account.move.line"]
        moveo = self.env["account.move"]
        processed = amlo

        valid = check_lines.filtered(
            lambda l: l.check_collection_state == "at_collection"
        )
        if not valid:
            raise UserError(
                _(
                    'Seleccione cheques en estado "Al cobro" pendientes de acreditación o rechazo.'
                )
            )

        for collection in valid.check_collection_id:
            group = valid.filtered(lambda l: l.check_collection_id == collection)
            if operation == "credit":
                counterpart = collection.bank_journal_id.default_account_id
                if not counterpart:
                    raise UserError(
                        _(
                            "El diario bancario '%s' no tiene cuenta contable configurada."
                        )
                        % collection.bank_journal_id.display_name
                    )
                journal = collection.bank_journal_id
                label_tpl = _("Acreditación cheque %s")
                new_state = "credited"
            else:
                counterpart = collection.rejected_account_id
                if not counterpart:
                    raise UserError(
                        _(
                            "No hay cuenta de cheques rechazados configurada para la moneda "
                            "'%(currency)s'.\n\nConfigúrela en Contabilidad > Configuración > "
                            "Cheques al cobro: cuentas.",
                            currency=collection.currency_id.display_name,
                        )
                    )
                journal = collection.journal_id
                label_tpl = _("Rechazo cheque %s")
                new_state = "rejected"

            for check in group:
                bridge_line = collection._get_bridge_line(check)
                if not bridge_line:
                    raise UserError(
                        _(
                            "No se encontró la línea de cuenta puente del cheque '%s'. "
                            "Verifique el envío al cobro."
                        )
                        % (check.numero_cheque or check.ref or check.name or "")
                    )
                ref = check.numero_cheque or check.ref or ""
                label = label_tpl % ref
                move = moveo.create(
                    {
                        "journal_id": journal.id,
                        "date": date,
                        "ref": label,
                        "company_id": collection.company_id.id,
                        "line_ids": [
                            (
                                0,
                                0,
                                {
                                    "name": label,
                                    "account_id": counterpart.id,
                                    "partner_id": check.partner_id.id
                                    if operation == "reject"
                                    else False,
                                    "debit": check.debit,
                                    "credit": 0.0,
                                    "currency_id": check.currency_id.id,
                                    "amount_currency": check.amount_currency,
                                    "collection_check_line_id": check.id,
                                },
                            ),
                            (
                                0,
                                0,
                                {
                                    "name": label,
                                    "account_id": collection.collection_account_id.id,
                                    "partner_id": check.partner_id.id,
                                    "debit": 0.0,
                                    "credit": check.debit,
                                    "currency_id": check.currency_id.id,
                                    "amount_currency": -check.amount_currency,
                                    "collection_check_line_id": check.id,
                                },
                            ),
                        ],
                    }
                )
                move.action_post()
                credit_bridge = move.line_ids.filtered(
                    lambda l: l.account_id == collection.collection_account_id
                )
                (bridge_line + credit_bridge).reconcile()
                check.write(
                    {
                        "check_collection_state": new_state,
                        "collection_settle_move_id": move.id,
                    }
                )
                processed |= check

            collection.message_post(
                body=_("%(verb)s %(count)s cheque(s): %(checks)s.")
                % {
                    "verb": _("Acreditados")
                    if operation == "credit"
                    else _("Rechazados"),
                    "count": len(group),
                    "checks": ", ".join(
                        group.mapped(lambda l: l.numero_cheque or l.ref or "")
                    ),
                }
            )
        return processed
