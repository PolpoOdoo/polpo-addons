from odoo import api, fields, models
from odoo.exceptions import UserError


class QappsStockPicking(models.Model):
    _inherit = "stock.picking"

    # copy=False: al duplicar un albarán no debe arrastrarse el estado de control.
    barcode = fields.Char(
        string="Código de barra", copy=False,
        help="Campo de ingreso del código de barras escaneado. Al escribir o escanear un "
        "código, se busca el producto correspondiente y se incrementa la cantidad "
        "controlada en el movimiento.",
    )
    checked_order = fields.Boolean(
        "Controlado", default=False, copy=False,
        help="Indica si todas las líneas del albarán fueron controladas mediante lectura "
        "de código de barras. Se marca automáticamente cuando todas las cantidades "
        "están verificadas.",
    )
    controller_user = fields.Char(
        string="Usuario Controlador", copy=False,
        help="Nombre del usuario que realizó el control de cantidades mediante lectura "
        "de códigos de barras.",
    )
    controller_date = fields.Datetime(
        string="Fecha de Control", copy=False,
        help="Fecha y hora (en hora local) en que se completó el control de cantidades "
        "del albarán mediante códigos de barras.",
    )

    def read_barcode(self, barcode):
        product_id = self.env["product.product"].search([("barcode", "=", barcode)])
        if not product_id:
            raise UserError(
                "No se encuentra producto asociado a dicho código de barra."
            )

        result = False
        for line in self.move_ids_without_package:
            if line.product_id.barcode == barcode:
                if line.qty_checked >= line.product_uom_qty:
                    raise UserError(
                        f"La cantidad controlada de {line.product_id.name} ya es igual a la reservada."
                    )
                line.qty_checked += 1
                self.barcode = None
                result = True
                break

        pendientes = (
            self.move_ids_without_package.filtered(
                lambda l: l.qty_checked != l.product_uom_qty
            )
            or []
        )
        if not self.checked_order and not pendientes:
            self.checked_order = True

        if not result:
            raise UserError("El producto leído no corresponde con esta orden.")

    def read_all_barcode(self):
        for line in self.move_ids_without_package:
            line.qty_checked = line.product_uom_qty

    @api.onchange("barcode")
    def onchange_barcode(self):
        barcode = self.barcode
        if barcode:
            self.read_barcode(barcode)

    # Movido a write(): el @api.onchange solo dispara en el form UI; un lector/
    # escáner que escribe checked_order por RPC no lo disparaba y el control no se
    # registraba. La lógica vive ahora en write().
    # @api.onchange("checked_order")
    # def onchange_checked_order(self):
    #     if self.checked_order:
    #         self.read_all_barcode()
    #         self.write_mail_message_checked_order(checked_order=True)

    def write_mail_message_checked_order(self, checked_order):
        username = (
            self.env["res.users"].browse(self.env.context.get("uid", self.env.uid)).name
        )
        controller_date = fields.Datetime.context_timestamp(
            self, fields.Datetime.now()
        ).replace(tzinfo=None)
        vals = {"controller_user": username, "controller_date": controller_date}
        if not checked_order:
            vals["checked_order"] = True
        self.write(vals)

        vals = {
            "message_type": "notification",
            "model": "stock.picking",
            "res_id": self.ids[0],
            "body": """<div>Control de cantidades realizados por:</div>
                        <ul>
                            <li>Usuario: {}</li>
                            <li>Fecha: {}</li>
                        </ul>
                    """.format(
                username, controller_date
            ),
        }
        self.env["mail.message"].create(vals)

    def write(self, vals):
        res = super(QappsStockPicking, self).write(vals)
        barcode = vals.get("barcode")
        if barcode:
            self.read_barcode(barcode)

        # Al completar el albarán, si se controló al menos una cantidad, se marca
        # como controlado (esto re-entra a write con checked_order=True).
        if "date_done" in vals and vals.get("date_done") and not self.checked_order:
            if any(line.qty_checked > 0 for line in self.move_ids_without_package):
                self.checked_order = True

        # Escaneo movido desde onchange: al marcar Controlado se completan las
        # cantidades y se registra el control. Se pasa checked_order=True para que
        # el write anidado (controller_user/date) no vuelva a entrar por esta rama.
        if "checked_order" in vals and vals.get("checked_order") is True:
            self.read_all_barcode()
            self.write_mail_message_checked_order(checked_order=True)
        return res

    def wizard_barcode_reader_action(self):
        context = self.env.context.copy()
        context["stock_picking_active_id"] = self.id
        return {
            "name": "Lector de códigos",
            "res_model": "qapps.barcode.reader",
            "view_mode": "form",
            "view_id": self.env.ref("qapps_codbarra.qapps_barcode_reader_view").id,
            "context": context,
            "target": "new",
            "type": "ir.actions.act_window",
        }
