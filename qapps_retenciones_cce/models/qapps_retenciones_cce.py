from odoo import api, fields, models
from odoo.exceptions import ValidationError


class QappsRetencionesCce(models.Model):
    _name = "qapps.retenciones.cce"
    _description = "Retenciones / Certificados de Credito Fiscal"

    name = fields.Char(
        string="Descripción",
        compute="_compute_name",
        store=True,
        help="Descripción calculada automáticamente a partir del tipo de aplicación y el nombre de la factura asociada.",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Factura",
        required=True,
        ondelete="cascade",
        help="Factura de venta a la que está vinculada esta retención o certificado de crédito fiscal.",
    )
    company_id = fields.Many2one(
        related="move_id.company_id",
        store=True,
        help="Empresa a la que pertenece esta retención, obtenida automáticamente desde la factura asociada.",
    )
    currency_id = fields.Many2one(
        related="move_id.currency_id",
        store=True,
        help="Moneda de la retención o CCE, obtenida automáticamente desde la moneda de la factura asociada.",
    )
    application_type = fields.Selection(
        [
            ("retention", "Retención en garantía"),
            ("certificate", "Certificado de crédito fiscal"),
        ],
        string="Tipo de aplicación",
        required=True,
        help="Tipo de retención: Retención en garantía (porcentaje retenido hasta finalizar obra) o Certificado de crédito fiscal (IVA retenido).",
    )
    base_calculation = fields.Selection(
        [("total", "Total factura"), ("base", "Base imponible")],
        string="Base de cálculo",
        help="Indica sobre qué valor se calcula la retención: total con impuestos o base imponible sin IVA. Solo aplica para Retención en garantía.",
    )
    invoice_line_ids = fields.Many2many(
        "account.move.line",
        "qapps_retencion_cce_move_line_rel",
        "retention_id",
        "line_id",
        string="Líneas de factura",
        help="Líneas específicas de la factura sobre las que aplica la retención. Si se deja vacío, la retención aplica sobre toda la factura. Solo aplica para Retención en garantía.",
    )
    percentage = fields.Float(
        string="Porcentaje",
        help="Porcentaje de retención a aplicar sobre la base de cálculo seleccionada. Solo aplica para retenciones en garantía.",
    )
    amount = fields.Monetary(
        string="Monto",
        compute="_compute_amount",
        store=True,
        help="Monto de la retención o CCE calculado automáticamente: para retención es (base × porcentaje / 100), para CCE es el monto total de IVA de la factura.",
    )
    account_id = fields.Many2one(
        "account.account",
        string="Cuenta",
        compute="_compute_account_id",
        store=True,
        readonly=False,
        help="Cuenta contable donde se registra la retención, calculada automáticamente desde la configuración de la empresa según el tipo de aplicación.",
    )
    project_id = fields.Many2one(
        "account.analytic.account",
        string="Proyecto / Obra",
        help="Proyecto u obra analítica a la que se imputa esta retención o certificado de crédito fiscal.",
    )
    state = fields.Selection(
        [("pending", "Pendiente de cobro"), ("paid", "Cobrado")],
        string="Estado",
        default="pending",
        readonly=True,
        help="Estado de la retención: Pendiente hasta que se registre el pago de devolución, Cobrado cuando el pago ha sido confirmado.",
    )
    payment_date = fields.Date(
        string="Fecha de cobro",
        help="Fecha en que se efectuó el cobro o devolución de la retención. Se completa automáticamente al confirmar el pago asociado.",
    )
    payment_id = fields.Many2one(
        "account.payment",
        string="Pago asociado",
        help="Pago registrado que liquida esta retención o CCE. Al confirmar el pago vinculado, la retención pasa a estado Cobrado.",
    )

    @api.depends("application_type", "move_id.name")
    def _compute_name(self):
        for record in self:
            type_label = dict(self._fields["application_type"].selection).get(
                record.application_type, ""
            )
            record.name = (
                f"{type_label} - {record.move_id.name}"
                if record.move_id
                else type_label
            )

    @api.depends(
        "application_type",
        "base_calculation",
        "percentage",
        "invoice_line_ids.price_total",
        "invoice_line_ids.price_subtotal",
        "move_id.amount_total",
        "move_id.amount_untaxed",
        "move_id.amount_tax",
    )
    def _compute_amount(self):
        for record in self:
            amount = 0.0
            if record.application_type == "retention":
                base = 0.0
                if record.invoice_line_ids:
                    if record.base_calculation == "total":
                        base = sum(record.invoice_line_ids.mapped("price_total"))
                    elif record.base_calculation == "base":
                        base = sum(record.invoice_line_ids.mapped("price_subtotal"))
                else:
                    if record.base_calculation == "total":
                        base = record.move_id.amount_total
                    elif record.base_calculation == "base":
                        base = record.move_id.amount_untaxed
                amount = base * (record.percentage / 100)
            elif record.application_type == "certificate":
                amount = record.move_id.amount_tax
            record.amount = amount

    @api.depends("application_type", "move_id.company_id")
    def _compute_account_id(self):
        for record in self:
            company = record.move_id.company_id
            if record.application_type == "retention":
                record.account_id = company.retention_warranty_account_id
            elif record.application_type == "certificate":
                record.account_id = company.certificate_credit_account_id
            else:
                record.account_id = False

    @api.onchange("application_type")
    def _onchange_application_type(self):
        if self.application_type == "certificate":
            self.base_calculation = False
            self.percentage = 0.0
            self.invoice_line_ids = [(5, 0, 0)]

    @api.constrains("application_type", "base_calculation")
    def _check_retention_requirements(self):
        for record in self:
            if record.application_type == "retention" and not record.base_calculation:
                raise ValidationError(
                    "La base de cálculo es obligatoria para Retención en garantía."
                )

    @api.constrains("application_type", "invoice_line_ids", "move_id")
    def _check_invoice_lines_belong_to_move(self):
        for record in self:
            if record.invoice_line_ids:
                if record.application_type != "retention":
                    raise ValidationError(
                        "Solo la Retención en garantía puede limitarse a líneas específicas de la factura."
                    )
                wrong = record.invoice_line_ids.filtered(
                    lambda l: l.move_id != record.move_id
                )
                if wrong:
                    raise ValidationError(
                        "Las líneas seleccionadas deben pertenecer a la misma factura."
                    )
