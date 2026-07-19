from odoo import models

# Nº de cuotas que MercadoPago ofrece en el checkout. El core lo fuerza a 1.
QAPPS_MP_INSTALLMENTS = 12


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _mercado_pago_prepare_preference_request_payload(self):
        """Override: fija en 12 las cuotas propuestas por MercadoPago.

        Reintroduce como override la customización de core perdida en el update
        de upstream (commit 7ff3e58ec). Se apoya en el payload que arma el core
        y solo pisa el valor de 'installments', para no duplicar el resto de la
        preferencia (items, payer, urls, etc.).
        """
        payload = super()._mercado_pago_prepare_preference_request_payload()
        payload.setdefault("payment_methods", {})["installments"] = (
            QAPPS_MP_INSTALLMENTS
        )
        return payload
