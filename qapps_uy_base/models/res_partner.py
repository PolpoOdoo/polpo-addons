from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..utils.comun import TIPO_DOC_CLIENTE
from ..utils.qapps_validacion_tipo_doc import validacion_ci, validacion_ruc

ERROR_TIPO_DOC_PERSON = (
    "Error, no puede seleccionar el Tipo Doc. RUT para las Individuales."
)
VALIDATION_ERROR_RUT = (
    "Error en la validación del número de Registro Único Tributario (RUT)."
)
VALIDATION_ERROR_CI = "Error en la validación de la Cédula de Identidad Uruguaya."


class ResPartner(models.Model):
    _inherit = "res.partner"

    razon_social = fields.Char(
        string="Razón social",
        required=False,
        help="Denominación legal del contacto tal como figura en los documentos "
        "fiscales uruguayos; se muestra en facturas y comprobantes.",
    )
    tipo_doc = fields.Selection(
        TIPO_DOC_CLIENTE,
        string="Tipo Doc.",
        required=False,
        help="Tipo de documento de identificación fiscal según la clasificación de "
        "la DGI (RUC, C.I., pasaporte, etc.). Determina la validación del número.",
    )

    @api.onchange("vat", "tipo_doc")
    def onchange_vat(self):
        vat = self.vat
        tipo_doc = self.tipo_doc
        if vat and tipo_doc:
            if tipo_doc == "2":
                if not validacion_ruc(vat):
                    raise ValidationError(VALIDATION_ERROR_RUT)
            elif tipo_doc == "3":
                if not validacion_ci(vat):
                    raise ValidationError(VALIDATION_ERROR_CI)

        if self.company_type == "person" and tipo_doc == "2":
            raise ValidationError(ERROR_TIPO_DOC_PERSON)

    @api.onchange("company_type")
    def onchange_company_type(self):
        if self.company_type == "person" and self.tipo_doc == "2":
            self.tipo_doc = False

    def is_from_uru(self):
        self.ensure_one()
        return bool(
            self.country_id and self.country_id.id == self.env.ref("base.uy").id
        )
