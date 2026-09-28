from odoo import models, fields, api, _
from zeep import Client

from .res_config_settings import CURRENCY_COTIZACION_MONEDA, CURRENCY_SERVICIO_FECHA_CIERRE, \
    CURRENCY_SERVICIO_COTIZACION, CURRENCY_EMAIL_NOTIF

STR_CODIGO_ISO = 'CodigoISO'
STR_TCC = 'TCC'
STR_FECHA = 'Fecha'

# El BCU no publica el codigo ISO de res.currency para todas las monedas: el
# euro viaja como 'EURO' y la Unidad Indexada como 'U.I.'. El resto coincide con
# el name de la moneda.
CODIGO_BCU = {
    'EUR': 'EURO',
    'UYI': 'U.I.',
}


class ResCurrency(models.Model):
    _inherit = 'res.currency'

    @api.model
    def exchange_task(self):
        currency_cotizacion_moneda = self.env['ir.config_parameter'].sudo().get_param(CURRENCY_COTIZACION_MONEDA)
        if not currency_cotizacion_moneda:
            return True

        currency_servicio_fecha_cierre = self.env['ir.config_parameter'].sudo().get_param(
            CURRENCY_SERVICIO_FECHA_CIERRE)
        client = Client(currency_servicio_fecha_cierre)
        last_update = client.service.Execute()

        active_currency = self.search([])
        currency_usd = list(filter(lambda x: x.name == 'USD', active_currency))
        if len(currency_usd) and (not currency_usd[0].date or currency_usd[0].date < last_update):
            self.update_currency_rates(active_currency, last_update)
        else:
            return True

    def update_currency_rates(self, active_currency, last_update):
        currency_servicio_cotizacion = self.env['ir.config_parameter'].sudo().get_param(CURRENCY_SERVICIO_COTIZACION)
        client = Client(currency_servicio_cotizacion)
        response = client.service.Execute({
                'Moneda': {'item': 0},
                'FechaDesde': last_update,
                'FechaHasta': last_update,
                'Grupo': 0
            })

        empresas = self.env["res.company"].search([('active', '=', True), ('parent_id', '=', False)])

        rates = response.datoscotizaciones['datoscotizaciones.dato']
        if not rates:
            self.send_email_missing_rate(False)
        for currency in active_currency:
            codigo = CODIGO_BCU.get(currency.name, currency.name)
            rate = [x for x in rates if x[STR_CODIGO_ISO] == codigo]
            if not rate:
                continue
            # res.currency.rate.rate son unidades de la moneda por 1 unidad de
            # la moneda de la compania, mientras que el BCU publica el TCC al
            # reves (pesos por unidad de la moneda), asi que se guarda su
            # inversa. Vale para todas las monedas, incluida la Unidad
            # Indexada: con la UI a 6,65 pesos se guarda 0,150376, y asi 1 UI
            # convertida con _convert da 6,65 pesos.
            valor = float('{:.12f}'.format(1 / rate[0][STR_TCC]))
            for company in empresas:
                self.env['res.currency.rate'].create({
                    'company_id': company.id,
                    'currency_id': currency.id,
                    'name': rate[0][STR_FECHA],
                    'rate': valor
                })

    def send_email_missing_rate(self, currency_name):
        currency_email_notif = self.env['ir.config_parameter'].sudo().get_param(CURRENCY_EMAIL_NOTIF)
        if currency_name:
            subject = f'No se pudo cargar la tasa de cambio de {currency_name} del día'
            body_html = f'<p>No fue posible obtener la tasa de cambio de <strong>{currency_name}</strong> ' \
                        f'correspondiente al día de hoy.<br/>' \
                        'Por favor, revise la configuración o ingrese la tasa manualmente para evitar ' \
                        'inconvenientes.<br/><br/>' \
                        'Saludos,</p>'
        else:
            subject = 'No se pudo cargar la tasa de cambio del día'
            body_html = '<p>No fue posible obtener la tasa de cambio correspondiente al día de hoy.<br/>' \
                         'Por favor, revise la configuración o ingrese la tasa manualmente para evitar ' \
                        'inconvenientes.<br/><br/>' \
                         'Saludos,</p>'

        mail_obj = self.env['mail.mail'].create({
            'subject': subject,
            'body_html': body_html,
            'email_to': currency_email_notif or 'info@polpo.uy',
            'email_from': self.env.company.email_formatted or 'info@polpo.uy',
        })
        mail_obj.send()

