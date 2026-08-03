# Copyright 2026 QAPPS
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    credit_override_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Autorizado por",
        readonly=True,
        copy=False,
        help="Usuario (Autorizador de crédito) que autorizó validar esta "
        "factura pese a la excepción de riesgo crediticio del cliente.",
    )
    credit_override_date = fields.Datetime(
        string="Fecha autorización",
        readonly=True,
        copy=False,
        help="Fecha y hora en que se autorizó la excepción crediticia de esta factura.",
    )
    credit_override_reason = fields.Text(
        string="Motivo autorización",
        readonly=True,
        copy=False,
        help="Justificación ingresada por el autorizador al aprobar la "
        "excepción crediticia. También queda registrada en el chatter.",
    )
    credit_override_flag = fields.Boolean(
        string="Operado bajo excepción",
        readonly=True,
        copy=False,
        help="Técnico: marca que la factura fue validada bajo una "
        "excepción crediticia autorizada. Activa el ribbon 'Bajo "
        "excepción' y evita reevaluar el riesgo al postear.",
    )
    credit_override_inherited = fields.Boolean(
        string="Excepción heredada del pedido",
        readonly=True,
        copy=False,
        help="Técnico: la excepción crediticia de esta factura fue heredada "
        "de su(s) pedido(s) de venta autorizados, no autorizada sobre la "
        "propia factura. La exención vale mientras la factura provenga "
        "íntegramente de sus pedidos (sin líneas por fuera del pedido ni "
        "superar su total); si deja de ser así, vuelve a evaluar riesgo.",
    )
    credit_override_origin_order_ids = fields.Many2many(
        comodel_name="sale.order",
        relation="account_move_credit_override_order_rel",
        string="Pedidos con excepción de origen",
        readonly=True,
        copy=False,
        help="Pedidos de venta operados bajo excepción crediticia de los "
        "que proviene esta factura (trazabilidad).",
    )
    # Warning informativo en factura borrador (paridad con sale.order)
    credit_warning_msg = fields.Html(
        compute="_compute_credit_warning_msg",
        string="Advertencia de crédito",
        sanitize=False,
        help="Técnico: lista HTML con los motivos por los que la "
        "validación requeriría autorización crediticia. Solo se calcula "
        "en facturas de cliente en borrador y alimenta el banner de "
        "advertencia de la factura.",
    )

    def _credit_risk_is_contado(self):
        """True si el comprobante a emitir es contado (no crédito).

        Reutiliza la única fuente de verdad de qapps_efactura
        (_es_contado_cfe: término de pago inmediato, o sin término con
        vencimiento "hoy"), que replica la lógica de fma_pago del CFE, para
        que la exención de riesgo coincida exactamente con lo que se emite
        como contado ante DGI. Si qapps_efactura no está instalado, cae al
        chequeo de término de pago inmediato.
        """
        self.ensure_one()
        if hasattr(self, "_es_contado_cfe"):
            return self._es_contado_cfe()
        immediate = self.env.ref(
            "account.account_payment_term_immediate", raise_if_not_found=False
        )
        return bool(immediate) and self.invoice_payment_term_id.id == immediate.id

    def _credit_risk_product_lines(self):
        """Líneas de producto de la factura (excluye secciones y notas)."""
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda line: line.display_type == "product"
        )

    def _credit_risk_source_orders(self):
        """Pedidos de venta de los que provienen las líneas de la factura."""
        self.ensure_one()
        return self._credit_risk_product_lines().sale_line_ids.order_id

    def _credit_risk_orders_total(self, orders):
        """Total de los pedidos de origen expresado en la moneda de la
        factura, para comparar contra amount_total."""
        self.ensure_one()
        total = 0.0
        conv_date = self.invoice_date or fields.Date.context_today(self)
        for order in orders:
            amount = order.amount_total
            if order.currency_id != self.currency_id:
                amount = order.currency_id._convert(
                    amount,
                    self.currency_id,
                    self.company_id,
                    conv_date,
                    round=False,
                )
            total += amount
        return total

    def _credit_risk_pure_from_sale_orders(self):
        """True si la factura proviene íntegramente de pedidos de venta (ya
        validados por el control de crédito al confirmarse) y no los
        supera: todas las líneas de producto tienen línea de pedido de origen
        y el total de la factura no excede el total de esos pedidos.

        Si a la factura se le agregan líneas por fuera del pedido, o su total
        supera lo pedido, deja de estar exenta y vuelve a evaluar riesgo al
        postear."""
        self.ensure_one()
        lines = self._credit_risk_product_lines()
        if not lines or any(not line.sale_line_ids for line in lines):
            return False
        orders = lines.sale_line_ids.order_id
        orders_total = self._credit_risk_orders_total(orders)
        return self.currency_id.compare_amounts(self.amount_total, orders_total) <= 0

    def _credit_risk_needs_validation(self):
        """La factura requiere validación de riesgo si es un comprobante
        crédito no cubierto por una autorización propia ni proveniente
        íntegramente de pedidos ya validados."""
        self.ensure_one()
        if self._credit_risk_is_contado():
            return False
        if self.credit_override_flag and not self.credit_override_inherited:
            return False
        return not self._credit_risk_pure_from_sale_orders()

    @api.depends(
        "partner_id",
        "amount_total",
        "currency_id",
        "state",
        "move_type",
        "credit_override_flag",
        "credit_override_inherited",
        "invoice_line_ids",
        "invoice_payment_term_id",
    )
    def _compute_credit_warning_msg(self):
        """
        Warning informativo sólo en facturas de cliente crédito directas
        (sin pedido origen) en borrador y sin autorización previa. Devuelve el
        contenido; el wrapper visual (alert) lo pone la vista.
        """
        for move in self:
            move.credit_warning_msg = False
            if move.move_type != "out_invoice" or move.state != "draft":
                continue
            if not move._credit_risk_needs_validation():
                continue
            partner = move.partner_id.commercial_partner_id
            if not partner:
                continue
            messages = partner._get_credit_exception_messages(
                extra_amount=move.risk_amount_total_currency,
                context_doc="invoice",
            )
            if messages:
                items = "".join("<li>%s</li>" % m for m in messages)
                move.credit_warning_msg = (
                    "<strong>%s</strong><ul class='mb-0'>%s</ul>"
                ) % (_("Advertencia de crédito:"), items)

    def risk_exception_msg(self):
        """
        Override: acumula TODAS las condiciones incumplidas, no sólo la primera
        (Caso 4).
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        messages = partner._get_credit_exception_messages(
            extra_amount=self.risk_amount_total_currency,
            context_doc="invoice",
        )
        if not messages:
            return ""
        return "\n".join(messages)

    def _first_invoice_exception_msg(self):
        """Override para usar nuestro wizard en lugar del OCA."""
        ret = False, False
        if self.env.context.get("bypass_risk", False):
            return ret
        for invoice in self.filtered(
            lambda x: x.move_type == "out_invoice"
            and not x.company_id.allow_overrisk_invoice_validation
            and x._credit_risk_needs_validation()
        ):
            exception_msg = invoice.risk_exception_msg()
            if exception_msg:
                ret = invoice, exception_msg
                break
        return ret

    def _credit_risk_apply_inherited_override(self):
        """Hereda a la factura la trazabilidad de la excepción crediticia
        autorizada en sus pedidos de origen: quién autorizó,
        cuándo, con qué motivo y de qué pedido(s) proviene. La marca de
        excepción se hereda sólo si la factura proviene íntegramente de los
        pedidos (_credit_risk_pure_from_sale_orders) y no tiene autorización
        propia; los pedidos de origen quedan registrados en cualquier caso."""
        for move in self.filtered(lambda m: m.move_type == "out_invoice"):
            orders = move._credit_risk_source_orders().filtered("credit_override_flag")
            if not orders:
                continue
            vals = {"credit_override_origin_order_ids": [(6, 0, orders.ids)]}
            has_own_override = (
                move.credit_override_flag and not move.credit_override_inherited
            )
            if not has_own_override and move._credit_risk_pure_from_sale_orders():
                last = orders.sorted(
                    lambda o: o.credit_override_date or fields.Datetime.now()
                )[-1]
                if len(orders) == 1:
                    reason = _("Heredada del pedido %(order)s: %(reason)s") % {
                        "order": orders.name,
                        "reason": orders.credit_override_reason or "",
                    }
                else:
                    reason = "\n".join(
                        _("%(order)s (autorizó %(user)s): %(reason)s")
                        % {
                            "order": order.name,
                            "user": order.credit_override_user_id.display_name,
                            "reason": order.credit_override_reason or "",
                        }
                        for order in orders
                    )
                vals.update(
                    {
                        "credit_override_flag": True,
                        "credit_override_inherited": True,
                        "credit_override_user_id": (last.credit_override_user_id.id),
                        "credit_override_date": last.credit_override_date,
                        "credit_override_reason": reason,
                    }
                )
            move.write(vals)

    def action_post(self):
        """Override para usar nuestro wizard de autorización."""
        invoice, exception_msg = self._first_invoice_exception_msg()
        if exception_msg and not self.env.context.get("from_validate_move_wiz", False):
            return (
                self.env["polpo.credit.override.wiz"]
                .create(
                    {
                        "exception_msg": exception_msg,
                        "partner_id": invoice.partner_id.commercial_partner_id.id,
                        "origin_reference": f"account.move,{invoice.id}",
                        "continue_method": "action_post",
                    }
                )
                .action_show()
            )
        if exception_msg and self.env.context.get("from_validate_move_wiz", False):
            raise ValidationError(
                _(
                    "El cliente %s está en excepción de riesgo.\n"
                    "Debe validar la factura desde la vista de formulario "
                    "para poder autorizar la excepción."
                )
                % invoice.partner_id.commercial_partner_id.display_name
            )
        self._credit_risk_apply_inherited_override()
        return super().action_post()
