# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # --- Cheques diferidos en cartera ---
    risk_deferred_checks_include = fields.Boolean(
        string="Incluir cheques diferidos",
        help="Incluir cheques diferidos en cartera en el cálculo de riesgo total.",
    )
    risk_deferred_checks_limit = fields.Monetary(
        string="Límite cheques diferidos",
        currency_field="risk_currency_id",
        help="Límite específico para cheques diferidos en cartera. Si el "
        "total de cheques diferidos supera este monto, las ventas y "
        "facturas del cliente quedan bloqueadas y requieren autorización. "
        "Setear 0 para no controlar este rubro.",
    )
    risk_deferred_checks = fields.Monetary(
        compute="_compute_risk_deferred_checks",
        string="Total cheques diferidos en cartera",
        currency_field="risk_currency_id",
        help="Monto total de cheques diferidos recibidos de este cliente "
        "que aún no fueron depositados (pendientes en cuenta de cheques).",
    )

    # --- Crédito adicional temporal ---
    additional_credit_amount = fields.Monetary(
        string="Crédito adicional",
        currency_field="risk_currency_id",
        tracking=True,
        help="Monto de crédito adicional temporal otorgado al cliente. "
        "Se suma al límite de crédito base si está dentro del período "
        "de vigencia (Vigencia desde - Vigencia hasta).",
    )
    additional_credit_date_from = fields.Date(
        string="Vigencia desde",
        tracking=True,
        help="Fecha desde la cual aplica el crédito adicional.",
    )
    additional_credit_date_to = fields.Date(
        string="Vigencia hasta",
        tracking=True,
        help="Fecha hasta la cual aplica el crédito adicional (inclusive).",
    )
    effective_credit_limit = fields.Monetary(
        compute="_compute_effective_credit_limit",
        string="Límite de crédito efectivo",
        currency_field="risk_currency_id",
        help="Límite de crédito base más el crédito adicional si está vigente "
        "a la fecha actual. Este es el límite que el sistema usa para "
        "evaluar el riesgo.",
    )
    # Indicador visual: si hay crédito adicional vigente hoy
    additional_credit_is_active = fields.Boolean(
        compute="_compute_effective_credit_limit",
        string="Crédito adicional vigente",
        help="Técnico: True si hay monto de crédito adicional con ambas "
        "fechas de vigencia cargadas y la fecha actual está dentro del "
        "período. Controla el ribbon 'Crédito adicional vigente' en la "
        "ficha del cliente.",
    )

    def _get_risk_deferred_checks_domain(self):
        """
        Cheques diferidos en cartera: account.move.line en la cuenta de
        cheques pendientes (in_hand_check_account), no conciliados,
        no depositados, del partner comercial.

        Lógica: los cheques recibidos generan un apunte debit en la cuenta
        de cheques en mano del diario. Mientras no estén depositados
        (check_deposit_id = False) y no estén conciliados, representan
        cheques en cartera.

        Requiere que account.move.line tenga el campo 'vencimiento'
        (proporcionado por qapps_cheque_info). Si no existe, devuelve dominio
        vacío.
        """
        aml_fields = self.env["account.move.line"]._fields
        if "vencimiento" not in aml_fields or "check_deposit_id" not in aml_fields:
            return [("id", "=", 0)]

        # Obtener las cuentas de "cheques en mano" de todos los diarios tipo banco
        # que no tienen cuenta bancaria (= diarios de cheques)
        check_journals = self.env["account.journal"].search(
            [
                ("type", "=", "bank"),
                ("bank_account_id", "=", False),
                ("company_id", "in", self.env.companies.ids),
            ]
        )
        in_hand_account_ids = set()
        for journal in check_journals:
            for line in journal.inbound_payment_method_line_ids:
                if line.payment_method_id.code == "manual" and line.payment_account_id:
                    in_hand_account_ids.add(line.payment_account_id.id)

        if not in_hand_account_ids:
            return [("id", "=", 0)]  # dominio vacío, no hay cuentas de cheques

        return self._get_risk_company_domain() + [
            ("account_id", "in", list(in_hand_account_ids)),
            ("reconciled", "=", False),
            ("debit", ">", 0),
            ("check_deposit_id", "=", False),
            ("parent_state", "=", "posted"),
            ("partner_id", "in", self.mapped("commercial_partner_id").ids),
            # Solo cheques con vencimiento futuro (diferidos)
            ("vencimiento", "!=", False),
            ("vencimiento", ">=", fields.Date.context_today(self)),
        ]

    @api.depends(
        "move_line_ids.amount_residual",
        "move_line_ids.reconciled",
        "move_line_ids.check_deposit_id",
        "move_line_ids.vencimiento",
    )
    def _compute_risk_deferred_checks(self):
        for partner in self:
            partner.risk_deferred_checks = 0.0
        customers = self.filtered(
            lambda p: p == p.commercial_partner_id
            or (p._origin and p._origin.id in p.commercial_partner_id.ids)
        )
        if not customers:
            return
        domain = customers._get_risk_deferred_checks_domain()
        if domain == [("id", "=", 0)]:
            return
        groups = self.env["account.move.line"]._read_group(
            domain=domain,
            groupby=["partner_id", "company_id"],
            aggregates=["debit:sum"],
        )
        for partner, company, total_debit in groups:
            commercial = partner.commercial_partner_id
            if commercial in customers:
                commercial.risk_deferred_checks = company.currency_id._convert(
                    total_debit,
                    commercial.risk_currency_id,
                    company,
                    fields.Date.context_today(self),
                    round=False,
                )

    @api.onchange(
        "additional_credit_amount",
        "additional_credit_date_from",
        "additional_credit_date_to",
    )
    def _onchange_additional_credit_coherence(self):
        """
        Warning no-bloqueante si el crédito adicional queda inconsistente:
        monto sin fechas, fechas sin monto, o fecha_desde > fecha_hasta.
        El compute ignora crédito adicional si falta cualquier dato, por lo
        que permitir guardar no genera cálculos erróneos — sólo avisamos.
        """
        amount = self.additional_credit_amount
        date_from = self.additional_credit_date_from
        date_to = self.additional_credit_date_to

        messages = []
        if amount and not (date_from and date_to):
            messages.append(
                _(
                    "Cargó un monto de crédito adicional sin completar ambas "
                    "fechas de vigencia. El crédito adicional NO se aplicará "
                    "hasta que ambas fechas estén cargadas."
                )
            )
        if (date_from or date_to) and not amount:
            messages.append(
                _(
                    "Cargó fechas de vigencia sin monto de crédito adicional. "
                    "El crédito adicional no tiene efecto."
                )
            )
        if date_from and date_to and date_from > date_to:
            messages.append(
                _(
                    "'Vigencia desde' (%(dfrom)s) es posterior a "
                    "'Vigencia hasta' (%(dto)s). El crédito adicional "
                    "NO se aplicará.",
                    dfrom=date_from,
                    dto=date_to,
                )
            )

        if messages:
            return {
                "warning": {
                    "title": _("Crédito adicional - datos incompletos"),
                    "message": "\n\n".join(messages),
                }
            }

    def _credit_limit_de_la_rama(self):
        """``credit_limit`` de la compañía activa, heredado de la casa central.

        ``res.partner.credit_limit`` es ``company_dependent`` en el core
        (``account/models/partner.py``), o sea que vive en una ``ir.property``
        por compañía. En una estructura con ramas —una sucursal hija de la casa
        central— el límite se carga una sola vez,
        desde la central, y la sucursal lo lee como 0.

        Ese 0 no da error: hace que la condición de riesgo total contra el
        límite de crédito (ver ``_get_credit_exception_messages``) se saltee en
        silencio, dejando los documentos de la sucursal SIN control de límite
        de crédito. Los demás rubros (pedidos, facturas abiertas, cheques
        diferidos, deuda vencida) no son ``company_dependent`` y sí se aplican,
        con lo cual el agujero pasa desapercibido.

        Se resuelve recorriendo la cadena de compañías desde la propia hacia la
        raíz y devolviendo el primer límite cargado. Un límite propio de la
        sucursal sigue ganando sobre el de la central: sólo se hereda cuando la
        sucursal no tiene valor.
        """
        self.ensure_one()
        # sudo() sobre la compañía: parent_ids es configuración, y un usuario
        # restringido a la sucursal no siempre puede leer la casa central
        # (AccessError por cids).
        cadena = self.env.company.sudo().parent_ids
        for company in reversed(cadena):
            limite = self.with_company(company).credit_limit
            if limite:
                return limite
        return self.credit_limit

    @api.depends(
        "credit_limit",
        "additional_credit_amount",
        "additional_credit_date_from",
        "additional_credit_date_to",
    )
    def _compute_effective_credit_limit(self):
        today = fields.Date.context_today(self)
        for partner in self:
            is_active = bool(
                partner.additional_credit_amount
                and partner.additional_credit_date_from
                and partner.additional_credit_date_to
                and partner.additional_credit_date_from
                <= today
                <= partner.additional_credit_date_to
            )
            partner.additional_credit_is_active = is_active
            base = partner._credit_limit_de_la_rama()
            partner.effective_credit_limit = (
                base + partner.additional_credit_amount if is_active else base
            )

    @api.depends(
        "additional_credit_amount",
        "additional_credit_date_from",
        "additional_credit_date_to",
    )
    def _compute_risk_remaining(self):
        """Override OCA: el crédito disponible se calcula contra el límite
        efectivo (base + adicional vigente), igual que _compute_risk_exception.
        """
        for record in self:
            limit = record.effective_credit_limit
            record.risk_remaining_value = limit - record.risk_total
            record.risk_remaining_percentage = (
                round(100 * (limit - record.risk_total) / limit) if limit else 0
            )

    @api.model
    def _risk_field_list(self):
        res = super()._risk_field_list()
        res.append(
            (
                "risk_deferred_checks",
                "risk_deferred_checks_limit",
                "risk_deferred_checks_include",
            )
        )
        return res

    def _get_field_risk_model_domain(self, field_name):
        if field_name == "risk_deferred_checks":
            return "account.move.line", self._get_risk_deferred_checks_domain()
        return super()._get_field_risk_model_domain(field_name)

    def _compute_risk_exception(self):
        """Override para usar effective_credit_limit en lugar de credit_limit."""
        risk_field_list = self._risk_field_list()
        for partner in self:
            amount = 0.0
            amount_exceeded = 0.0
            risk_exception = False
            for risk_field in risk_field_list:
                field_value = getattr(partner, risk_field[0], 0.0)
                max_value = getattr(partner, risk_field[1], 0.0)
                include = getattr(partner, risk_field[2], False)
                if max_value and field_value > max_value:
                    risk_exception = True
                    amount_exceeded += field_value - max_value
                if include:
                    # Normalizar a 0 los rubros negativos: un rubro incluido con
                    # saldo a favor (NC > facturas, créditos, otra cuenta con saldo
                    # acreedor) no debe compensar la exposición de otros rubros y
                    # enmascarar un exceso de riesgo real. Solo suma exposición
                    # positiva.
                    amount += max(field_value, 0.0)
            effective_limit = partner.effective_credit_limit
            if effective_limit and amount > effective_limit:
                risk_exception = True
                amount_exceeded = amount - effective_limit
            partner.risk_total = amount
            partner.risk_amount_exceeded = amount_exceeded
            partner.risk_exception = risk_exception

    def _get_credit_exception_messages(self, extra_amount=0.0, context_doc=None):
        """
        Evalúa TODAS las condiciones de riesgo del partner y devuelve una lista
        con todos los motivos de bloqueo encontrados (no solo el primero).

        :param extra_amount: monto adicional a considerar sobre el riesgo actual
            (ej: total del pedido que se está confirmando) en la moneda de riesgo
            del partner.
        :param context_doc: 'sale' | 'invoice' | None. Permite evaluar límites
            específicos según el contexto del documento.
        :return: lista de strings (motivos). Lista vacía = sin excepciones.
        """
        self.ensure_one()
        messages = []
        partner = self.commercial_partner_id

        # Forzar recompute de campos de riesgo stored para evitar valores
        # desactualizados. En OCA account_financial_risk v17 estos campos son
        # stored/computed y pueden no reflejar el estado actual si el trigger
        # no se disparó (ej: factura recién vencida).
        risk_fields = [
            "risk_invoice_unpaid",
            "risk_sale_order",
            "risk_invoice_open",
            "risk_total",
            "risk_exception",
        ]
        existing = [f for f in risk_fields if f in partner._fields]
        if existing:
            partner.invalidate_recordset(existing)
            # Forzar recompute: leer los campos dispara el compute si están
            # invalidados en cache
            for f in existing:
                getattr(partner, f)
        # Recomputar nuestros campos propios
        partner.invalidate_recordset(
            [
                "risk_deferred_checks",
                "effective_credit_limit",
            ]
        )

        # 1. Deuda vencida — solo si el cliente tiene activado el control
        # de facturas impagas (risk_invoice_unpaid_include). Sin ese check,
        # el cliente no está parametrizado para control de crédito y no se
        # bloquea por deuda vencida.
        unpaid = partner.risk_invoice_unpaid or 0.0
        if partner.risk_invoice_unpaid_include and unpaid > 0:
            messages.append(
                _(
                    "El cliente tiene deuda vencida por %(amount)s %(currency)s.",
                    amount=partner.risk_currency_id.format(unpaid),
                    currency=partner.risk_currency_id.name,
                )
            )

        # 2. Límite específico de pedidos (solo en contexto venta)
        if (
            context_doc == "sale"
            and partner.risk_sale_order_limit
            and (
                (partner.risk_sale_order + extra_amount) > partner.risk_sale_order_limit
            )
        ):
            messages.append(
                _(
                    "Este pedido excede el límite de riesgo de pedidos: "
                    "%(current)s + %(extra)s > %(limit)s %(currency)s.",
                    current=partner.risk_currency_id.format(partner.risk_sale_order),
                    extra=partner.risk_currency_id.format(extra_amount),
                    limit=partner.risk_currency_id.format(
                        partner.risk_sale_order_limit
                    ),
                    currency=partner.risk_currency_id.name,
                )
            )

        # 3. Límite específico de facturas abiertas (solo en contexto factura)
        if (
            context_doc == "invoice"
            and partner.risk_invoice_open_limit
            and (
                (partner.risk_invoice_open + extra_amount)
                > partner.risk_invoice_open_limit
            )
        ):
            messages.append(
                _(
                    "Esta factura excede el límite de facturas abiertas: "
                    "%(current)s + %(extra)s > %(limit)s %(currency)s.",
                    current=partner.risk_currency_id.format(partner.risk_invoice_open),
                    extra=partner.risk_currency_id.format(extra_amount),
                    limit=partner.risk_currency_id.format(
                        partner.risk_invoice_open_limit
                    ),
                    currency=partner.risk_currency_id.name,
                )
            )

        # 4. Límite de cheques diferidos
        if partner.risk_deferred_checks_limit and (
            partner.risk_deferred_checks > partner.risk_deferred_checks_limit
        ):
            messages.append(
                _(
                    "El cliente excede el límite de cheques diferidos en cartera: "
                    "%(current)s > %(limit)s %(currency)s.",
                    current=partner.risk_currency_id.format(
                        partner.risk_deferred_checks
                    ),
                    limit=partner.risk_currency_id.format(
                        partner.risk_deferred_checks_limit
                    ),
                    currency=partner.risk_currency_id.name,
                )
            )

        # 5. Riesgo total vs límite efectivo (credit_limit + crédito adicional vigente)
        if partner.effective_credit_limit and (
            (partner.risk_total + extra_amount) > partner.effective_credit_limit
        ):
            messages.append(
                _(
                    "Supera el riesgo financiero total: "
                    "%(current)s + %(extra)s > %(limit)s %(currency)s.",
                    current=partner.risk_currency_id.format(partner.risk_total),
                    extra=partner.risk_currency_id.format(extra_amount),
                    limit=partner.risk_currency_id.format(
                        partner.effective_credit_limit
                    ),
                    currency=partner.risk_currency_id.name,
                )
            )

        return messages
