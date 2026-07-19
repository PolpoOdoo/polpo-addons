from odoo import fields, models


class QappsStockMove(models.Model):
    _inherit = "stock.move"

    # copy=False: la cantidad controlada no debe copiarse al duplicar el movimiento.
    qty_checked = fields.Float(
        "Controlado", digits="Product Unit of Measure", default=0, copy=False,
        help="Cantidad de unidades del producto ya verificadas mediante lectura de "
        "código de barras. Se incrementa de a 1 por cada escaneo correcto.",
    )
