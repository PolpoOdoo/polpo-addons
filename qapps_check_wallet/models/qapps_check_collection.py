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
        ondelete="restrict",
        help='Asiento que mueve los cheques de la cuenta de cartera a la cuenta puente "al cobro". '
        "No se puede eliminar mientras el envío lo referencie: con el ondelete por "
        "defecto, borrar el asiento dejaba el envío en estado enviado y sin asiento. "
        "Para deshacerlo hay que volver el envío a borrador.",
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

    @api.constrains("state", "move_id")
    def _check_sent_has_move(self):
        """Un envío enviado al cobro sin asiento es un dato imposible: los
        cheques figuran fuera de la cartera pero no hay línea puente contra la
        cual acreditarlos ni rechazarlos."""
        for rec in self:
            if rec.state == "sent" and not rec.move_id:
                raise ValidationError(
                    _(
                        "El envío al cobro '%s' no puede quedar en estado enviado "
                        "sin asiento contable."
                    )
                    % rec.display_name
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
        self._check_checks_available()

    def _check_checks_available(self):
        """Ningún cheque del envío puede estar ya comprometido en otro envío al
        cobro. El dominio del formulario los esconde del diálogo de selección,
        pero no gobierna las escrituras; y los envíos anteriores a este control
        pueden tener cheques enganchados de más. Sin esta validación el envío se
        valida igual, le roba el cheque al envío original y la acreditación
        queda sin línea puente que conciliar."""
        self.ensure_one()
        for check in self.check_payment_ids:
            owner = self._collection_of_bridge_line(self._get_open_bridge_line(check))
            if owner and owner != self:
                raise UserError(
                    _(
                        "El cheque %(check)s ya fue enviado al cobro en %(collection)s. "
                        "Retírelo de este envío o reviértalo primero desde el envío original.",
                        check=check.numero_cheque or check.ref or check.name or "",
                        collection=owner.display_name,
                    )
                )
            if check.check_collection_state:
                situaciones = dict(
                    check._fields["check_collection_state"]._description_selection(
                        self.env
                    )
                )
                raise UserError(
                    _(
                        "El cheque %(check)s ya está en el circuito de cobranza "
                        "(situación: %(situacion)s). Retírelo de este envío.",
                        check=check.numero_cheque or check.ref or check.name or "",
                        situacion=situaciones.get(check.check_collection_state),
                    )
                )
            if check.reconciled:
                raise UserError(
                    _(
                        "El cheque %s ya está conciliado: salió de la cartera por otro "
                        "documento. Retírelo de este envío."
                    )
                    % (check.numero_cheque or check.ref or check.name or "")
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
            if not move.line_ids:
                raise UserError(
                    _(
                        "El asiento de envío al cobro de '%s' quedó sin líneas; "
                        "no se envió nada al cobro."
                    )
                    % rec.display_name
                )
            move.action_post()
            if move.state != "posted":
                raise UserError(
                    _("No se pudo contabilizar el asiento del envío al cobro '%s'.")
                    % rec.display_name
                )

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
            # Primero se suelta el asiento y recién después se borra: move_id es
            # ondelete='restrict', y además el envío no puede quedar en estado
            # enviado sin asiento en ningún momento.
            move = rec.move_id
            rec.check_payment_ids.write({"check_collection_state": False})
            rec.write({"state": "draft", "move_id": False})
            if move:
                move.line_ids.remove_move_reconcile()
                if move.state == "posted":
                    move.button_cancel()
                move.with_context(force_delete=True).unlink()
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
    @api.model
    def _collection_of_bridge_line(self, bridge_line):
        """Envío al cobro dueño del asiento donde vive una línea puente.

        Se busca en sudo a propósito: es una verificación de integridad y un
        usuario parado en una sola sucursal no ve los envíos de la madre; si no
        lo viera, dejaría de detectar el conflicto."""
        if not bridge_line:
            return self.browse()
        owner = self.sudo().search([("move_id", "=", bridge_line.move_id.id)], limit=1)
        return self.browse(owner.id) if owner else self.browse()

    @api.model
    def _get_open_bridge_lines(self, check):
        """Líneas puente abiertas de un cheque, en cualquier envío al cobro.

        La línea puente se reconoce por su estructura, no por la configuración
        del momento: es un debe sin conciliar de un asiento de envío al cobro.
        Los dos filtros importan. collection_check_line_id marca también la
        línea de cartera del asiento de envío y las dos del asiento de
        acreditación o rechazo, y la línea de banco de una acreditación queda
        sin conciliar, así que sin acotar se devolvería una línea que no es el
        puente. Y no se filtra por las cuentas puente configuradas hoy porque el
        mapeo por moneda puede haber cambiado después del envío: la cuenta vieja
        dejaría de estar en la lista y la línea se volvería invisible."""
        candidates = self.env["account.move.line"].search(
            [
                ("collection_check_line_id", "=", check.id),
                ("debit", ">", 0),
                ("reconciled", "=", False),
                ("parent_state", "=", "posted"),
            ]
        )
        return candidates.filtered(
            lambda line: bool(self._collection_of_bridge_line(line))
        )

    @api.model
    def _get_open_bridge_line(self, check):
        """Línea puente abierta de un cheque, en cualquier envío al cobro."""
        return self._get_open_bridge_lines(check)[:1]

    def _get_bridge_line(self, check):
        """Línea abierta en la cuenta puente correspondiente a un cheque.

        Prefiere la de la cuenta puente de este envío y, si no hay, toma la que
        exista en cualquier otro envío: el cheque puede estar colgado de un
        envío distinto del que generó su asiento, o el mapeo de cuentas por
        moneda puede haber cambiado después del envío. Sin ese segundo intento
        la acreditación cortaba con "no se encontró la línea de cuenta puente"."""
        self.ensure_one()
        lines = self._get_open_bridge_lines(check)
        propias = lines.filtered(
            lambda line: line.account_id == self.collection_account_id
        )
        return (propias or lines)[:1]

    @api.model
    def _realign_collection_links(self, check_lines):
        """Devuelve cada cheque al envío al cobro que efectivamente lo
        contabilizó, cuando su check_collection_id apunta a otro.

        Es la reparación del dato roto por el reenvío: mientras el vínculo miente,
        el envío original figura sin cheques y la acreditación se contabiliza
        con las cuentas y el banco del envío equivocado. Queda registrado en el
        chatter de los dos documentos."""
        for check in check_lines:
            owner = self._collection_of_bridge_line(self._get_open_bridge_line(check))
            stale = check.check_collection_id
            if not owner or owner == stale:
                continue
            ref = check.numero_cheque or check.ref or check.name or ""
            check.check_collection_id = owner.id
            owner.message_post(
                body=_(
                    "El cheque %(check)s volvió a este envío: figuraba en %(stale)s, "
                    "que no tiene su asiento de envío al cobro."
                )
                % {"check": ref, "stale": stale.display_name or _("otro envío")}
            )
            if stale:
                stale.message_post(
                    body=_(
                        "El cheque %(check)s se devolvió a %(owner)s, que es el envío "
                        "que generó su asiento."
                    )
                    % {"check": ref, "owner": owner.display_name}
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
        # Antes de agrupar: el cheque tiene que estar colgado del envío que lo
        # contabilizó, porque de ahí salen el banco, la moneda y las cuentas.
        self._realign_collection_links(valid)

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
                                    # La cuenta sale de la línea puente encontrada,
                                    # no del mapeo actual: si el mapeo por moneda
                                    # cambió después del envío, acreditar contra la
                                    # cuenta nueva dejaría la vieja descuadrada y la
                                    # conciliación no cruzaría.
                                    "account_id": bridge_line.account_id.id,
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
                    lambda l: l.account_id == bridge_line.account_id
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
