from odoo import api, fields, models

CURRENCY_COTIZACION_MONEDA = "qapps.currency_cotizacion_moneda"
CURRENCY_SERVICIO_FECHA_CIERRE = "qapps.currency_servicio_fecha_cierre"
CURRENCY_SERVICIO_COTIZACION = "qapps.currency_servicio_cotizacion"
CURRENCY_EMAIL_NOTIF = "qapps.currency_email_notif"
CRON_NAME = "Actualizar tasa de cambio."
WSDL_FECHA_CIERRE = (
    "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsultimocierre?wsdl"
)
WSDL_COTIZACION = (
    "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/awsbcucotizaciones?wsdl"
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    currency_cotizacion_moneda = fields.Boolean(
        string="Actualización automática tasa cambio",
        help="Activa la tarea programada (cron) que consulta el BCU para actualizar automáticamente las tasas de cambio de las monedas activas.",
    )
    currency_servicio_fecha_cierre = fields.Char(
        string="Servicio fecha cierre (wsdl)",
        help="URL del servicio web WSDL del BCU que informa la última fecha de cierre disponible para cotizaciones.",
    )
    currency_servicio_cotizacion = fields.Char(
        string="Servicio cotizaciones (wsdl)",
        help="URL del servicio web WSDL del BCU que retorna las cotizaciones de monedas (USD, EUR, UI, etc.) para una fecha dada.",
    )
    currency_email_notif = fields.Char(
        string="Email notificación",
        help="Dirección de correo electrónico a la que se envía una notificación cuando no se puede obtener la tasa de cambio del día desde el BCU.",
    )

    def set_values(self):
        res = super(ResConfigSettings, self).set_values()
        self.env["ir.config_parameter"].set_param(
            CURRENCY_COTIZACION_MONEDA, self.currency_cotizacion_moneda
        )
        self.env["ir.config_parameter"].set_param(
            CURRENCY_SERVICIO_FECHA_CIERRE, self.currency_servicio_fecha_cierre
        )
        self.env["ir.config_parameter"].set_param(
            CURRENCY_SERVICIO_COTIZACION, self.currency_servicio_cotizacion
        )
        self.env["ir.config_parameter"].set_param(
            CURRENCY_EMAIL_NOTIF, self.currency_email_notif
        )
        return res

    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        config_param = self.env["ir.config_parameter"].sudo()
        res.update(
            {
                "currency_cotizacion_moneda": config_param.get_param(
                    CURRENCY_COTIZACION_MONEDA, default=True
                ),
                "currency_servicio_fecha_cierre": config_param.get_param(
                    CURRENCY_SERVICIO_FECHA_CIERRE, default=WSDL_FECHA_CIERRE
                ),
                "currency_servicio_cotizacion": config_param.get_param(
                    CURRENCY_SERVICIO_COTIZACION, default=WSDL_COTIZACION
                ),
                "currency_email_notif": config_param.get_param(
                    CURRENCY_EMAIL_NOTIF, default="info@polpo.uy"
                ),
            }
        )
        return res

    @api.onchange("currency_cotizacion_moneda")
    def _onchange_activate_load(self):
        cron_job = (
            self.env["ir.cron"]
            .sudo()
            .search(
                [
                    ("name", "=", CRON_NAME),
                    ("active", "=", not self.currency_cotizacion_moneda),
                ]
            )
        )
        cron_job.sudo().update({"active": self.currency_cotizacion_moneda})
        if not self.currency_cotizacion_moneda:
            self.currency_servicio_fecha_cierre = ""
            self.currency_servicio_cotizacion = ""

    def write(self, values):
        result = super(ResConfigSettings, self).write(values)
        if values.get("currency_cotizacion_moneda", False):
            cron_job = self.env["ir.cron"].sudo().search([("name", "=", CRON_NAME)])
            cron_job.sudo().method_direct_trigger()
        return result
