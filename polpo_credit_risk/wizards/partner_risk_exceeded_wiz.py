# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, models
from odoo.exceptions import AccessError, UserError

# Misma allowlist que polpo.credit.override.wiz (CR-01): la continuación del
# wizard existe solo para reanudar la confirmación de ventas y el posteo de
# facturas bloqueadas por riesgo.
ALLOWED_CONTINUE_METHODS = {
    "sale.order": "action_confirm",
    "account.move": "action_post",
}


class PartnerRiskExceededWiz(models.TransientModel):
    """Endurece el wizard OCA de riesgo excedido.

    El wizard de account_financial_risk tiene ACL de creación/escritura para
    TODO usuario interno y su ``button_continue`` ejecuta por reflexión
    cualquier ``continue_method`` sobre cualquier modelo (Reference sin
    restricción) con ``bypass_risk=True``: cualquier usuario podía saltarse
    el control de crédito por RPC, y de paso era un gadget de ejecución de
    métodos arbitrarios. Se agrega chequeo de grupo (Autorizador de crédito)
    + allowlist de modelo/método, mismo criterio que el wizard propio.
    """

    _inherit = "partner.risk.exceeded.wiz"

    def button_continue(self):
        self.ensure_one()
        if not self.env.user.has_group("polpo_credit_risk.group_credit_authorizer"):
            raise AccessError(
                _(
                    "No tiene permisos para autorizar excepciones crediticias.\n"
                    "Contacte a un usuario con perfil de Autorizador de crédito."
                )
            )
        origin = self.origin_reference
        if origin and self.continue_method != ALLOWED_CONTINUE_METHODS.get(
            origin._name
        ):
            raise UserError(
                _(
                    "Operación no permitida: la autorización de crédito solo "
                    "puede reanudar la confirmación de pedidos o el posteo de "
                    "facturas."
                )
            )
        return super().button_continue()
