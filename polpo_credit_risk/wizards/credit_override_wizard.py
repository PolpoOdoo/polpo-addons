# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError

# Allowlist de continuación (CR-01): el wizard existe solo para reanudar la
# confirmación de ventas y el posteo de facturas bloqueadas por riesgo. Todo
# par modelo/método fuera de esto es un gadget de ejecución vía RPC.
ALLOWED_CONTINUE_METHODS = {
    "sale.order": "action_confirm",
    "account.move": "action_post",
}


class PolpoCreditOverrideWiz(models.TransientModel):
    _name = "polpo.credit.override.wiz"
    _description = "Autorización de excepción crediticia"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        readonly=True,
        string="Cliente",
    )
    exception_msg = fields.Text(
        readonly=True,
        string="Motivo del bloqueo",
        help="Técnico: motivos de bloqueo crediticio en texto plano (uno "
        "por línea), tal como los devuelve la evaluación de riesgo del "
        "cliente. Se usa para el registro en el chatter.",
    )
    exception_msg_html = fields.Html(
        compute="_compute_exception_msg_html",
        string="Motivos del bloqueo",
        sanitize=False,
        readonly=True,
        help="Técnico: los motivos del bloqueo renderizados como lista "
        "HTML para mostrarlos en el wizard, igual que el banner de la "
        "cotización/factura.",
    )
    override_reason = fields.Text(
        string="Motivo de la autorización",
        help="Justificación para autorizar esta excepción.",
    )
    origin_reference = fields.Reference(
        lambda self: [
            (m.model, m.name)
            for m in self.env["ir.model"]
            .sudo()
            .search([("model", "in", list(ALLOWED_CONTINUE_METHODS))])
        ],
        string="Documento origen",
        help="Técnico: pedido de venta o factura cuya operación quedó "
        "bloqueada por riesgo y se reanuda al autorizar. Restringido a "
        "los modelos de la allowlist del wizard.",
    )
    continue_method = fields.Char(
        help="Técnico: método a reanudar sobre el documento origen tras "
        "autorizar (action_confirm para pedidos, action_post para "
        "facturas). Validado contra la allowlist antes de ejecutarse.",
    )
    # Computed para visibilidad robusta del botón "Autorizar y continuar"
    # En Odoo 17 el atributo `groups` en botones de wizard
    # footer no siempre se aplica de forma consistente; esto lo refuerza.
    can_authorize = fields.Boolean(
        compute="_compute_can_authorize",
        help="Técnico: True si el usuario actual pertenece al grupo "
        "'Autorizador de crédito'. Controla la visibilidad del botón "
        "'Autorizar y continuar' y del campo de justificación.",
    )

    def _compute_exception_msg_html(self):
        """Renderiza los motivos (una línea c/u) como lista <ul><li>,
        igual que el banner de la cotización. message_post sigue usando
        exception_msg (texto plano) para el chatter."""
        for rec in self:
            lines = rec.exception_msg.splitlines() if rec.exception_msg else []
            lines = [escape(line) for line in lines if line.strip()]
            if lines:
                items = "".join("<li>%s</li>" % line for line in lines)
                rec.exception_msg_html = Markup("<ul class='mb-0'>%s</ul>" % items)
            else:
                rec.exception_msg_html = False

    def _compute_can_authorize(self):
        is_authorizer = self.env.user.has_group(
            "polpo_credit_risk.group_credit_authorizer"
        )
        for rec in self:
            rec.can_authorize = is_authorizer

    def action_show(self):
        self.ensure_one()
        partner_name = self.partner_id.display_name or ""
        if partner_name:
            name = _("Riesgo crediticio excedido para: %s") % partner_name
        else:
            name = _("Riesgo crediticio excedido")
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def button_authorize(self):
        """Autorizar la excepción. Solo usuarios del grupo credit_authorizer."""
        self.ensure_one()
        if not self.env.user.has_group("polpo_credit_risk.group_credit_authorizer"):
            raise AccessError(
                _(
                    "No tiene permisos para autorizar excepciones crediticias.\n"
                    "Contacte a un usuario con perfil de Autorizador de crédito."
                )
            )

        origin = self.origin_reference
        if not origin:
            return

        # Defensa en profundidad: el Reference ya restringe el modelo, pero un
        # write por RPC podría colar otro continue_method.
        if self.continue_method != ALLOWED_CONTINUE_METHODS.get(origin._name):
            raise UserError(
                _(
                    "Operación no permitida: la autorización de crédito solo "
                    "puede continuar la confirmación de un pedido de venta o "
                    "el posteo de una factura."
                )
            )

        # Registrar la autorización en el documento
        override_vals = {
            "credit_override_user_id": self.env.uid,
            "credit_override_date": fields.Datetime.now(),
            "credit_override_reason": self.override_reason or "",
            "credit_override_flag": True,
        }
        origin.write(override_vals)

        # Registrar en chatter. message_post escapa strings; se usa Markup
        # para que los tags HTML se rendericen
        # Los valores interpolados se escapan automáticamente por Markup,
        # protegiendo contra inyección en display_name / override_reason.
        exception_html = Markup("<br/>").join(
            self.exception_msg.splitlines() if self.exception_msg else []
        )
        reason_html = (
            Markup("<b>%s</b> %s") % (_("Justificación:"), self.override_reason)
            if self.override_reason
            else Markup("")
        )
        body = Markup(
            "<b>%(title)s</b><br/>"
            "<b>%(lbl_partner)s</b> %(partner)s<br/>"
            "<b>%(lbl_exception)s</b><br/>%(exception)s<br/>"
            "<b>%(lbl_user)s</b> %(user)s<br/>"
            "%(reason)s"
        ) % {
            "title": _("Autorización de excepción crediticia"),
            "lbl_partner": _("Cliente:"),
            "partner": self.partner_id.display_name,
            "lbl_exception": _("Motivo del bloqueo:"),
            "exception": exception_html,
            "lbl_user": _("Autorizado por:"),
            "user": self.env.user.display_name,
            "reason": reason_html,
        }
        origin.message_post(body=body, message_type="notification")

        # Continuar con la operación original (con bypass_risk)
        return getattr(origin.with_context(bypass_risk=True), self.continue_method)()
