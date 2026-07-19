from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    is_check_journal = fields.Boolean(
        string="Diario de cheques",
        help="Marcar para incluir este diario en el reporte Cheques en cartera.",
    )
