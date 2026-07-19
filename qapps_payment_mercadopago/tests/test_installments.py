# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMercadoPagoInstallments(TransactionCase):
    """El payload de la preferencia de MercadoPago debe pedir 12 cuotas
    (customización QApps), no 1 como el core."""

    def test_payload_installments_is_12(self):
        provider = self.env.ref(
            'payment_mercado_pago.payment_provider_mercado_pago',
            raise_if_not_found=False,
        )
        if not provider:
            self.skipTest("No hay provider de MercadoPago en datos de demo")

        method = provider.payment_method_ids[:1] or self.env['payment.method'].search([], limit=1)
        if not method:
            self.skipTest("No hay payment.method disponible")

        partner = self.env['res.partner'].create({'name': 'QApps MP Test'})
        tx = self.env['payment.transaction'].create({
            'provider_id': provider.id,
            'payment_method_id': method.id,
            'reference': 'QAPPS-MP-TEST',
            'amount': 1000.0,
            'currency_id': self.env.ref('base.UYU').id,
            'partner_id': partner.id,
        })

        payload = tx._mercado_pago_prepare_preference_request_payload()
        self.assertEqual(payload['payment_methods']['installments'], 12)
