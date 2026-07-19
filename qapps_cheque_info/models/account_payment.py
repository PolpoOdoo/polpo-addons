from odoo import fields, models

CHEQUE_HELP_NUMERO = "Número del cheque asociado al pago."
CHEQUE_HELP_VENC = "Fecha de vencimiento del cheque asociado al pago."
CHEQUE_HELP_NOTE = "Observaciones del pago (por ejemplo, datos del cheque)."


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    numero_cheque = fields.Char("Número de cheque", help=CHEQUE_HELP_NUMERO)
    vencimiento = fields.Date("Vencimiento", help=CHEQUE_HELP_VENC)
    note = fields.Text("Observaciones", help=CHEQUE_HELP_NOTE)

    def _create_payment_common(self, payment_vals):
        payment_vals.update(
            {
                "numero_cheque": self.numero_cheque,
                "vencimiento": self.vencimiento,
                "note": self.note,
            }
        )
        return payment_vals

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        return self._create_payment_common(payment_vals)

    def _create_payment_vals_from_batch(self, batch_result):
        payment_vals = super()._create_payment_vals_from_batch(batch_result)
        return self._create_payment_common(payment_vals)


class AccountPayment(models.Model):
    _inherit = "account.payment"

    numero_cheque = fields.Char("Número de cheque", help=CHEQUE_HELP_NUMERO)
    vencimiento = fields.Date("Vencimiento", help=CHEQUE_HELP_VENC)
    note = fields.Text("Observaciones", help=CHEQUE_HELP_NOTE)

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if not (payment.numero_cheque or payment.vencimiento or payment.note):
                continue
            move_lines = payment.move_id.line_ids._all_reconciled_lines()
            move_lines.write(
                {
                    "numero_cheque": payment.numero_cheque,
                    "vencimiento": payment.vencimiento,
                    "note": payment.note,
                }
            )
        return res


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    numero_cheque = fields.Char(
        "Número de cheque",
        help="Número del cheque propagado desde el pago, vinculado a esta línea del "
        "asiento contable.",
    )
    vencimiento = fields.Date(
        "Vencimiento",
        help="Fecha de vencimiento del cheque propagado desde el pago, vinculada a "
        "esta línea del asiento contable.",
    )
    note = fields.Text(
        "Observaciones",
        help="Observaciones propagadas desde el pago, vinculadas a esta línea del "
        "asiento contable.",
    )
