from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    retention_warranty_account_id = fields.Many2one(
        related="company_id.retention_warranty_account_id",
        string="Cuenta Retenciones en garantía",
        readonly=False,
        check_company=True,
        help="Cuenta contable de la empresa donde se registran las retenciones en garantía sobre facturas de clientes. Obtenida desde la configuración de la compañía.",
    )
    certificate_credit_account_id = fields.Many2one(
        related="company_id.certificate_credit_account_id",
        string="Cuenta certificados de crédito fiscal",
        readonly=False,
        check_company=True,
        help="Cuenta contable de la empresa donde se registran los certificados de crédito fiscal (CCE) de IVA retenido. Obtenida desde la configuración de la compañía.",
    )
