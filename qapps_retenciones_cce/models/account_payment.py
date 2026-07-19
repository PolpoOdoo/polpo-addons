from odoo import api, fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    application_type = fields.Selection(
        [
            ("retention", "Retención en garantía"),
            ("certificate", "Certificado de crédito fiscal"),
        ],
        string="Tipo de aplicación",
        help="Indica si el pago corresponde a una devolución de retención en garantía o a la aplicación de un certificado de crédito fiscal (CCE).",
    )
    retention_id = fields.Many2one(
        "qapps.retenciones.cce",
        string="Aplicación a regularizar",
        domain="[('state', '=', 'pending'), ('application_type', '=', application_type), ('move_id.partner_id','=',partner_id)]",
        help="Retención o CCE pendiente de cobro que este pago regulariza. Al confirmar el pago, la retención pasa a estado Cobrado.",
    )

    @api.onchange("retention_id")
    def _onchange_retention_id(self):
        if self.retention_id:
            self.amount = self.retention_id.amount

    @api.onchange("application_type")
    def _onchange_application_type(self):
        self.retention_id = False

    @api.depends("application_type", "partner_id", "company_id")
    def _compute_destination_account_id(self):
        super()._compute_destination_account_id()
        for payment in self:
            if (
                payment.application_type == "retention"
                and payment.company_id.retention_warranty_account_id
            ):
                payment.destination_account_id = (
                    payment.company_id.retention_warranty_account_id
                )
            elif (
                payment.application_type == "certificate"
                and payment.company_id.certificate_credit_account_id
            ):
                payment.destination_account_id = (
                    payment.company_id.certificate_credit_account_id
                )

    def action_post(self):
        res = super().action_post()
        for payment in self:
            if payment.application_type and payment.retention_id:
                payment.retention_id.write(
                    {
                        "state": "paid",
                        "payment_id": payment.id,
                        "payment_date": payment.date,
                    }
                )
        return res
