from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    retention_cce_ids = fields.One2many(
        "qapps.retenciones.cce",
        "move_id",
        string="Retenciones / CCE",
        help="Líneas de retenciones en garantía y/o certificados de crédito fiscal (CCE) asociados a esta factura. Al confirmar la factura se generan los asientos de reclasificación.",
    )
    reclass_retencion_move_id = fields.Many2one(
        "account.move",
        string="Asiento reclasificación retenciones",
        copy=False,
        help="Asiento de reclasificación generado al postear esta factura con retenciones/CCE.",
    )

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        for move in self:
            if (
                move.state == "posted"
                and move.move_type in ("out_invoice", "out_refund")
                and move.retention_cce_ids
            ):
                if not move.reclass_retencion_move_id:
                    move._create_retention_reclassification_entry()
                else:
                    # Re-posteo tras un reset a borrador: NO se duplica el asiento
                    # (se preserva el existente), pero el core rompió el reconcile
                    # entre el receivable de la factura y el del asiento de
                    # reclasificación (button_draft -> remove_move_reconcile). Hay
                    # que RE-RECONCILIAR para que el saldo de la factura vuelva a
                    # quedar neto de la retención; si no, la cuenta corriente del
                    # cliente muestra el importe completo (la retención "desaparece").
                    move._reconcile_retention_reclass()
        return res

    def _reconcile_retention_reclass(self):
        """Reconcilia el receivable de la factura con el del asiento de
        reclasificación de retenciones cuando quedó suelto (típicamente tras un
        reset a borrador + re-posteo). Idempotente: si ya está conciliado no hace
        nada."""
        self.ensure_one()
        reclass = self.reclass_retencion_move_id
        if not reclass or reclass.state != "posted":
            return
        receivable_lines = self.line_ids.filtered(
            lambda l: l.display_type == "payment_term"
            or l.account_type in ("asset_receivable", "liability_payable")
        )
        if not receivable_lines:
            return
        receivable_account = receivable_lines[0].account_id
        reclass_receivables = reclass.line_ids.filtered(
            lambda l: l.account_id == receivable_account
        )
        if not reclass_receivables or all(l.reconciled for l in reclass_receivables):
            return
        (receivable_lines + reclass_receivables).reconcile()

    def button_cancel(self):
        res = super().button_cancel()
        for move in self:
            reclass = move.reclass_retencion_move_id
            if move.state == "cancel" and reclass and reclass.state == "posted":
                move._reverse_retention_reclass(reclass)
        return res

    def _reverse_retention_reclass(self, reclass):
        """Al CANCELAR una factura con retenciones, el asiento de reclasificación
        (un 'entry' separado) queda posteado y huérfano: ya no responde a ninguna
        factura vigente y sobrestima la contrapartida de la retención. Se reversa
        (cancel=True: la reversa se postea y se concilia con el original -> net
        cero, sin residuos en cuentas abiertas) y se limpia el vínculo. NO se
        borra: un entry posteado que consumió secuencia y no es el último de la
        cadena no puede eliminarse (check_move_sequence_chain). Si luego se
        re-postea la factura, _post genera un asiento nuevo."""
        self.ensure_one()
        reclass._reverse_moves(
            default_values_list=[
                {
                    "date": reclass.date,
                    "ref": ("Reversa %s" % (reclass.ref or "")).strip(),
                }
            ],
            cancel=True,
        )
        self.reclass_retencion_move_id = False

    def write(self, vals):
        res = super().write(vals)
        # El asiento de reclasificación se arma con el nombre de la factura ANTES de
        # que efactura le asigne el número de CFE (efactura corre más afuera en el MRO
        # y renombra después con self.write({'name': ...})). Se sincroniza el ref del
        # asiento ante cualquier cambio de nombre, sin acoplar efactura.
        if vals.get("name"):
            for move in self:
                if move.reclass_retencion_move_id:
                    move.reclass_retencion_move_id.ref = f"Retenciones {move.name}"
        return res

    def _create_retention_reclassification_entry(self):
        self.ensure_one()
        receivable_lines = self.line_ids.filtered(
            lambda l: l.display_type == "payment_term"
            or l.account_type in ("asset_receivable", "liability_payable")
        )
        if not receivable_lines:
            return

        receivable_account = receivable_lines[0].account_id
        partner = self.partner_id
        # retention.amount está en la moneda de la FACTURA. Si la factura es en
        # moneda extranjera (EI factura en USD), el asiento debe llevar
        # currency_id + amount_currency y el debit/credit convertido a moneda
        # compañía al TC de la factura; si no, se contabilizaría el monto en
        # moneda compañía y el reconcile contra el receivable en USD generaría
        # diferencia de cambio espuria y dejaría el residual mal.
        move_currency = self.currency_id
        company_currency = self.company_id.currency_id
        conv_date = self.date or fields.Date.context_today(self)

        # Primer pase: armar cada retención con su monto en moneda factura y su
        # conversión individual a moneda compañía.
        entries = []
        for retention in self.retention_cce_ids:
            if not retention.account_id or not retention.amount:
                continue

            if self.move_type == "out_invoice":
                debit_account_id = retention.account_id.id
                credit_account_id = receivable_account.id
                amount = retention.amount
            elif self.move_type == "out_refund":
                debit_account_id = receivable_account.id
                credit_account_id = retention.account_id.id
                amount = retention.amount
            else:
                continue

            entries.append(
                {
                    "name": retention.name or f"Retención {self.name}",
                    "debit_account_id": debit_account_id,
                    "credit_account_id": credit_account_id,
                    "amount": amount,  # en moneda factura
                    "company_amount": move_currency._convert(
                        amount, company_currency, self.company_id, conv_date
                    ),
                }
            )

        if not entries:
            return

        # Reparto del centavo de redondeo: con varias retenciones en moneda
        # extranjera, sum(round(amount_i·TC)) puede diferir de round(sum·TC) y
        # dejar el residual de la factura descuadrado en moneda compañía contra
        # el receivable (que se valuó con un único redondeo). Se ajusta la
        # retención de mayor monto para que la suma coincida con la conversión
        # única del total. Cada par debe/haber usa el mismo company_amount, así
        # que el asiento sigue balanceado. Con una sola retención o factura en
        # moneda compañía, diff = 0 (sin cambios de comportamiento).
        objetivo = move_currency._convert(
            sum(e["amount"] for e in entries),
            company_currency,
            self.company_id,
            conv_date,
        )
        diff = company_currency.round(
            objetivo - sum(e["company_amount"] for e in entries)
        )
        if diff:
            mayor = max(entries, key=lambda e: e["company_amount"])
            mayor["company_amount"] = company_currency.round(
                mayor["company_amount"] + diff
            )

        lines_vals = []
        for e in entries:
            lines_vals.append(
                {
                    "name": e["name"],
                    "account_id": e["debit_account_id"],
                    "debit": e["company_amount"],
                    "credit": 0.0,
                    "partner_id": partner.id,
                    "currency_id": move_currency.id,
                    "amount_currency": e["amount"],
                }
            )
            lines_vals.append(
                {
                    "name": e["name"],
                    "account_id": e["credit_account_id"],
                    "debit": 0.0,
                    "credit": e["company_amount"],
                    "partner_id": partner.id,
                    "currency_id": move_currency.id,
                    "amount_currency": -e["amount"],
                }
            )

        journal = (
            self.env["account.journal"].search(
                [("type", "=", "general"), ("company_id", "=", self.company_id.id)],
                limit=1,
            )
            or self.journal_id
        )

        reclass_move = self.env["account.move"].create(
            {
                "ref": f"Retenciones {self.name}",
                "journal_id": journal.id,
                "date": self.date,
                "move_type": "entry",
                "company_id": self.company_id.id,
                "partner_id": self.partner_id.id,
                "line_ids": [(0, 0, val) for val in lines_vals],
            }
        )

        reclass_move.action_post()
        self.reclass_retencion_move_id = reclass_move

        reclass_receivables = reclass_move.line_ids.filtered(
            lambda l: l.account_id == receivable_account
        )
        (receivable_lines + reclass_receivables).reconcile()
