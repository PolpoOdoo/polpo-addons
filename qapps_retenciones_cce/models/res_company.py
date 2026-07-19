from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    retention_warranty_account_id = fields.Many2one(
        "account.account",
        string="Cuenta Retenciones en garantía",
        help="Cuenta contable donde se contabilizan las retenciones en garantía realizadas sobre facturas de clientes. Se usa en el asiento de reclasificación al confirmar la factura.",
    )
    certificate_credit_account_id = fields.Many2one(
        "account.account",
        string="Cuenta certificados de crédito fiscal",
        help="Cuenta contable donde se contabilizan los certificados de crédito fiscal (CCE) de IVA retenido por el cliente. Se usa en el asiento de reclasificación.",
    )
