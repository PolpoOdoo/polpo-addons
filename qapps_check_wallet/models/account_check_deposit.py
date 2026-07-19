from odoo import _, models
from odoo.exceptions import UserError


class AccountCheckDeposit(models.Model):
    _inherit = "account.check.deposit"

    def get_all_checks(self):
        """Override del botón 'Traer todos los cheques' del depósito OCA para
        excluir los cheques que ya fueron enviados a un endoso o a un envío al
        cobro (aunque su documento esté todavía en borrador). Sin esto, un
        cheque en borrador de otro circuito podría engancharse en un depósito."""
        self.ensure_one()
        if not self.in_hand_check_account_id:
            raise UserError(
                _(
                    "En la configuración del diario '%s', en la pestaña 'Pagos "
                    "entrantes', debe configurar una Cuenta de cobros pendientes "
                    "para el método de pago 'Manual (entrante)'."
                )
                % self.journal_id.display_name
            )
        all_pending_checks = self.env["account.move.line"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("reconciled", "=", False),
                ("account_id", "=", self.in_hand_check_account_id.id),
                ("debit", ">", 0),
                ("check_deposit_id", "=", False),
                ("check_endorsement_id", "=", False),
                ("check_collection_id", "=", False),
                ("currency_id", "=", self.currency_id.id),
                ("parent_state", "=", "posted"),
            ]
        )
        if all_pending_checks:
            self.message_post(body=_("Traer todos los cheques recibidos"))
            all_pending_checks.write({"check_deposit_id": self.id})
        else:
            raise UserError(
                _(
                    "No hay cheques recibidos en la cuenta '%(account)s' en la moneda "
                    "'%(currency)s' que no estén ya en este depósito.",
                    account=self.in_hand_check_account_id.display_name,
                    currency=self.currency_id.display_name,
                )
            )
