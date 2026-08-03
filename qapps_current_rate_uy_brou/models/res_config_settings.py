from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    brou_currency_update = fields.Boolean(
        string="Actualización automática tasa cambio - BROU",
        help="Activa la tarea programada (cron) que obtiene diariamente las tasas de compra y venta del dólar desde el sitio web del BROU. Guarda la tasa de venta en la moneda DOL y la tasa de compra en la moneda DOC."
    )

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].set_param('brou.currency_update', self.brou_currency_update)

    def get_values(self):
        res = super().get_values()
        res.update({
            'brou_currency_update': self.env['ir.config_parameter'].sudo().get_param('brou.currency_update', default=False),
        })
        return res

    @api.onchange('brou_currency_update')
    def _onchange_brou_currency_update(self):
        cron_job = self.env['ir.cron'].sudo().search([('name', '=', 'Actualizar tasas de cambio BROU')])
        if cron_job:
            cron_job.sudo().update({'active': self.brou_currency_update})
