# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    credit_override_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Autorizado por",
        readonly=True,
        copy=False,
        help="Usuario (Autorizador de crédito) que autorizó validar esta "
        "factura pese a la excepción de riesgo crediticio del cliente.",
    )
    credit_override_date = fields.Datetime(
        string="Fecha autorización",
        readonly=True,
        copy=False,
        help="Fecha y hora en que se autorizó la excepción crediticia de esta factura.",
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
        help="Técnico: marca que la factura fue validada bajo una "
        "excepción crediticia autorizada. Activa el ribbon 'Bajo "
        "excepción' y evita reevaluar el riesgo al postear.",
    )
    # Warning informativo en factura borrador (paridad con sale.order)
    credit_warning_msg = fields.Html(
        compute="_compute_credit_warning_msg",
        string="Advertencia de crédito",
        sanitize=False,
        help="Técnico: lista HTML con los motivos por los que la "
        "validación requeriría autorización crediticia. Solo se calcula "
        "en facturas de cliente en borrador y alimenta el banner de "
        "advertencia de la factura.",
    )

    @api.depends(
        "partner_id",
        "amount_total",
        "currency_id",
        "state",
        "move_type",
        "credit_override_flag",
    )
    def _compute_credit_warning_msg(self):
        """
        Warning informativo sólo en facturas de cliente en borrador y sin
        autorización previa. Devuelve el contenido; el wrapper visual (alert)
        lo pone la vista.
        """
        for move in self:
            move.credit_warning_msg = False
            if move.move_type != "out_invoice" or move.state != "draft":
                continue
            if move.credit_override_flag:
                continue
            partner = move.partner_id.commercial_partner_id
            if not partner:
                continue
            messages = partner._get_credit_exception_messages(
                extra_amount=move.risk_amount_total_currency,
                context_doc="invoice",
            )
            if messages:
                items = "".join("<li>%s</li>" % m for m in messages)
                move.credit_warning_msg = (
                    "<strong>%s</strong><ul class='mb-0'>%s</ul>"
                ) % (_("Advertencia de crédito:"), items)

    def risk_exception_msg(self):
        """
        Override: acumula TODAS las condiciones incumplidas, no sólo la primera

        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        messages = partner._get_credit_exception_messages(
            extra_amount=self.risk_amount_total_currency,
            context_doc="invoice",
        )
        if not messages:
            return ""
        return "\n".join(messages)

    def _first_invoice_exception_msg(self):
        """Override para usar nuestro wizard en lugar del OCA."""
        ret = False, False
        if self.env.context.get("bypass_risk", False):
            return ret
        for invoice in self.filtered(
            lambda x: x.move_type == "out_invoice"
            and not x.credit_override_flag
            and not x.company_id.allow_overrisk_invoice_validation
        ):
            exception_msg = invoice.risk_exception_msg()
            if exception_msg:
                ret = invoice, exception_msg
                break
        return ret

    def action_post(self):
        """Override para usar nuestro wizard de autorización."""
        invoice, exception_msg = self._first_invoice_exception_msg()
        if exception_msg and not self.env.context.get("from_validate_move_wiz", False):
            return (
                self.env["polpo.credit.override.wiz"]
                .create(
                    {
                        "exception_msg": exception_msg,
                        "partner_id": invoice.partner_id.commercial_partner_id.id,
                        "origin_reference": f"account.move,{invoice.id}",
                        "continue_method": "action_post",
                    }
                )
                .action_show()
            )
        if exception_msg and self.env.context.get("from_validate_move_wiz", False):
            raise ValidationError(
                _(
                    "El cliente %s está en excepción de riesgo.\n"
                    "Debe validar la factura desde la vista de formulario "
                    "para poder autorizar la excepción."
                )
                % invoice.partner_id.commercial_partner_id.display_name
            )
        return super().action_post()
