from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


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

    # ------------------------------------------------------------------
    # Un cheque, un documento
    # ------------------------------------------------------------------
    def _check_document_label(self):
        """Documentos de cartera que reclaman este cheque, para los mensajes."""
        self.ensure_one()
        labels = []
        if self.check_deposit_id:
            labels.append(
                _("boleta de depósito %s") % self.check_deposit_id.display_name
            )
        if self.check_endorsement_id:
            labels.append(_("endoso %s") % self.check_endorsement_id.display_name)
        if self.check_collection_id:
            labels.append(
                _("envío al cobro %s") % self.check_collection_id.display_name
            )
        return labels

    @api.constrains("check_deposit_id", "check_endorsement_id", "check_collection_id")
    def _check_single_check_document(self):
        """Un cheque en cartera sale una sola vez: no puede estar a la vez en una
        boleta de depósito, en un endoso y en un envío al cobro. Los formularios
        lo filtran por dominio, pero el dominio solo gobierna el diálogo de
        selección: cualquier escritura sobre el one2many (una importación, un
        duplicado, un cambio hecho desde otra pantalla) lo saltea. El invariante
        vive acá, en el modelo."""
        for line in self:
            labels = line._check_document_label()
            if len(labels) > 1:
                raise ValidationError(
                    _(
                        "El cheque %(check)s no puede estar en más de un documento "
                        "a la vez. Hoy figura en: %(docs)s.",
                        check=line.numero_cheque or line.ref or line.name or line.id,
                        docs=", ".join(labels),
                    )
                )

    def _check_collection_reassignment(self, new_collection_id):
        """Impide robarle un cheque al envío al cobro que ya lo contabilizó.

        Agregar a un envío en borrador un cheque que ya estaba al cobro reasigna
        el one2many y le cambia el check_collection_id al apunte: el envío
        original queda vacío y el cheque apunta a un envío que no tiene su
        asiento ni su línea puente, con lo cual la acreditación después no la
        encuentra. La única reasignación admitida es la que devuelve
        el cheque al envío dueño de su línea puente abierta, que es la
        corrección de un vínculo ya desactualizado."""
        collection_model = self.env["qapps.check.collection"]
        for line in self:
            if not line.check_collection_state:
                continue
            if line.check_collection_id.id == new_collection_id:
                continue
            bridge = collection_model._get_open_bridge_line(line)
            owner = collection_model._collection_of_bridge_line(bridge)
            if owner and owner.id == new_collection_id:
                continue
            raise UserError(
                _(
                    "El cheque %(check)s ya fue enviado al cobro en %(collection)s. "
                    "Retírelo de este envío o reviértalo primero desde el envío original.",
                    check=line.numero_cheque or line.ref or line.name or line.id,
                    collection=(owner or line.check_collection_id).display_name
                    or _("otro envío"),
                )
            )

    def write(self, vals):
        if "check_collection_id" in vals:
            self._check_collection_reassignment(vals["check_collection_id"])
        return super().write(vals)
