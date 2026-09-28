from odoo import api, fields, models


class QappsBarcodeReaderLine(models.TransientModel):
    _name = "qapps.barcode.reader.line"
    _description = "Permite ingresar los numeros leidos por el barcode"

    barcode = fields.Char(
        string="Código de barra",
        help="Código escaneado. Al ingresarlo se busca el producto en el traslado activo "
        "y se incrementa en 1 su cantidad controlada.",
    )
    reader_id = fields.Many2one("qapps.barcode.reader", string="Lector")
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        readonly=True,
        help="Producto identificado a partir del código de barras escaneado.",
    )
    reserved_availability = fields.Float(
        "Reservado",
        digits="Product Unit of Measure",
        default=0,
        readonly=True,
        help="Cantidad demandada del producto en el traslado, contra la que "
        "se compara la cantidad controlada.",
    )
    qty_checked = fields.Float(
        "Controlado",
        digits="Product Unit of Measure",
        default=0,
        readonly=True,
        help="Cantidad ya verificada por escaneo para este producto en el traslado.",
    )

    @api.onchange("barcode")
    def onchange_barcode(self):
        if self.barcode:
            stock_picking_active_id = self._context.get(
                "stock_picking_active_id", False
            )
            if stock_picking_active_id:
                picking = self.env["stock.picking"].browse(stock_picking_active_id)
                picking.read_barcode(self.barcode)
                self._load_info_picking(picking)

    def _load_info_picking(self, picking):
        for line in picking.move_ids_without_package:
            if line.product_id.barcode == self.barcode:
                self.product_id = line.product_id.id
                self.reserved_availability = line.product_uom_qty
                self.qty_checked = line.qty_checked
                break


class QappsBarcodeReader(models.TransientModel):
    _name = "qapps.barcode.reader"
    _description = "Permite ingresar los numeros leidos por el barcode"

    barcode_line = fields.One2many(
        "qapps.barcode.reader.line", "reader_id", string="Lineas de detalles"
    )

    def action_done(self):
        return True
