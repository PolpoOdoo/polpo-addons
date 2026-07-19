from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    check_endorsement_id = fields.Many2one(
        comodel_name="qapps.check.endorsement",
        string="Endoso de cheque",
        copy=False,
        check_company=True,
        help="Endoso por el cual este cheque fue entregado a un proveedor y salió de la cartera.",
    )
    check_collection_id = fields.Many2one(
        comodel_name="qapps.check.collection",
        string="Envío al cobro",
        copy=False,
        check_company=True,
        help="Envío por el cual este cheque fue entregado al banco al cobro.",
    )
    check_collection_state = fields.Selection(
        selection=[
            ("at_collection", "Al cobro"),
            ("credited", "Acreditado"),
            ("rejected", "Rechazado"),
        ],
        string="Situación al cobro",
        copy=False,
        help="Situación del cheque dentro del circuito de cobranza bancaria.",
    )
    collection_check_line_id = fields.Many2one(
        comodel_name="account.move.line",
        string="Cheque al cobro de origen",
        copy=False,
        index=True,
        help="En las líneas de puente, banco o rechazados, apunta a la línea de "
        "cheque en cartera que les dio origen, para mantener la trazabilidad.",
    )
    collection_settle_move_id = fields.Many2one(
        comodel_name="account.move",
        string="Asiento de acreditación / rechazo",
        copy=False,
        help="Asiento contable que acreditó en banco o registró el rechazo de este cheque al cobro.",
    )
