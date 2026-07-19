from odoo import models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def button_confirm(self):
        super().button_confirm()
        for order in self:
            order.picking_ids.move_ids.quantity = 0
        return True
