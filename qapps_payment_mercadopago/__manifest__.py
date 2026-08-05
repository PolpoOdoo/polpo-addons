{
    "name": "MercadoPago 12 cuotas - Polpo",
    "summary": "Habilita hasta 12 cuotas en el checkout de MercadoPago",
    "description": """
        Qué hace: override de payment.transaction que fija en 12 el número de
        cuotas (installments) propuestas por MercadoPago al armar el payload de
        la preferencia de pago. El core de Odoo lo fuerza a 1.

        Para qué sirve: en Uruguay/LatAm el pago en cuotas con tarjeta vía
        MercadoPago es habitual; forzar 1 cuota deshabilita esa opción en el
        checkout de la tienda.

        Origen: reintroduce como override una customización de core que se
        perdía en cada actualización de Odoo desde upstream (commit 7ff3e58ec
        "Ajuste 12 cuotas MercadoPago", que patcheaba directamente
        payment_mercado_pago/models/payment_transaction.py).
    """,
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "category": "Accounting/Payment",
    "version": "17.0.1.0.2",
    "depends": ["payment_mercado_pago"],
    "license": 'LGPL-3',
    "images": ["static/description/banner.png"],
    "installable": True,
}
