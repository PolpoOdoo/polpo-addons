# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    credit_override_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Autorizado por",
        readonly=True,
        copy=False,
        help="Usuario (Autorizador de crédito) que autorizó confirmar este "
        "pedido pese a la excepción de riesgo crediticio del cliente.",
    )
    credit_override_date = fields.Datetime(
        string="Fecha autorización",
        readonly=True,
        copy=False,
        help="Fecha y hora en que se autorizó la excepción crediticia de este pedido.",
    )
    credit_override_reason = fields.Text(
        string="Motivo autorización",
        readonly=True,
        copy=False,
        help="Justificación ingresada por el autorizador al aprobar la "
        "excepción crediticia. También queda registrada en el chatter.",
    )
    credit_override_flag = fields.Boolean(
        string="Operado bajo excepción",
        readonly=True,
        copy=False,
        help="Técnico: marca que el pedido fue confirmado bajo una "
        "excepción crediticia autorizada. Activa el ribbon 'Bajo "
        "excepción' y evita reevaluar el riesgo al confirmar.",
    )
    # Warning informativo en cotización (Caso 3)
    credit_warning_msg = fields.Html(
        compute="_compute_credit_warning_msg",
        string="Advertencia de crédito",
        sanitize=False,
        help="Técnico: lista HTML con los motivos por los que la "
        "confirmación requeriría autorización crediticia. Solo se calcula "
        "en estados borrador/enviado y alimenta el banner de advertencia "
        "de la cotización.",
    )

    def _credit_risk_is_contado(self):
        """True si el pedido es contado (término de pago inmediato).

        Regla única del control de crédito: sólo los documentos crédito
        validan riesgo. Un pedido contado se confirma sin validar, en
        coherencia con la factura contado que emitirá (). Sin término
        de pago se considera crédito (validación conservadora)."""
        self.ensure_one()
        immediate = self.env.ref(
            "account.account_payment_term_immediate", raise_if_not_found=False
        )
        return bool(immediate) and self.payment_term_id == immediate

    @api.depends(
        "partner_invoice_id",
        "amount_total",
        "currency_id",
        "state",
        "credit_override_flag",
        "payment_term_id",
    )
    def _compute_credit_warning_msg(self):
        """
        Warning informativo sólo en pedidos crédito en estados previos a la
        confirmación (draft/sent). Una vez confirmado o autorizado, no se
        muestra. Devuelve sólo el contenido (lista). El wrapper visual lo pone
        la vista.
        """
        for order in self:
            order.credit_warning_msg = False
            if order.state not in ("draft", "sent"):
                continue
            if order.credit_override_flag:
                continue
            if order._credit_risk_is_contado():
                continue
            if not order.partner_invoice_id:
                continue
            partner = order.partner_invoice_id.commercial_partner_id
            if not partner:
                continue
            extra_amount = order._get_risk_extra_amount(partner)
            messages = partner._get_credit_exception_messages(
                extra_amount=extra_amount,
                context_doc="sale",
            )
            if messages:
                items = "".join("<li>%s</li>" % m for m in messages)
                order.credit_warning_msg = (
                    "<strong>%s</strong><ul class='mb-0'>%s</ul>"
                ) % (_("Advertencia de crédito:"), items)

    def _get_risk_extra_amount(self, partner):
        """Convierte amount_total a la moneda de riesgo del partner."""
        self.ensure_one()
        if not self.amount_total:
            return 0.0
        return self.currency_id._convert(
            self.amount_total,
            partner.risk_currency_id,
            self.company_id,
            self.date_order
            and self.date_order.date()
            or fields.Date.context_today(self),
            round=False,
        )

    def evaluate_risk_message(self, partner):
        """
        Override: ahora acumula TODAS las condiciones incumplidas,
        no sólo la primera (Caso 4).
        """
        self.ensure_one()
        extra_amount = self._get_risk_extra_amount(partner)
        messages = partner._get_credit_exception_messages(
            extra_amount=extra_amount,
            context_doc="sale",
        )
        if not messages:
            return ""
        return "\n".join(messages)

    def action_confirm(self):
        """Override: si ya fue autorizado (credit_override_flag), bypass risk."""
        if not self.env.context.get("bypass_risk", False):
            for order in self:
                if order.credit_override_flag:
                    continue
                if order._credit_risk_is_contado():
                    continue
                partner = order.partner_invoice_id.commercial_partner_id
                exception_msg = order.evaluate_risk_message(partner)
                if exception_msg:
                    return (
                        self.env["polpo.credit.override.wiz"]
                        .create(
                            {
                                "exception_msg": exception_msg,
                                "partner_id": partner.id,
                                "origin_reference": f"{order._name},{order.id}",
                                "continue_method": "action_confirm",
                            }
                        )
                        .action_show()
                    )
        return super(SaleOrder, self.with_context(bypass_risk=True)).action_confirm()
