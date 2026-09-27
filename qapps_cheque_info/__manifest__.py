{
    "name": "Check Info on Payments and Journal Items / Cheque Info en Pagos y Apuntes",
    "summary": "Check number, due date and notes on the payment, carried to the journal items. / Número de cheque, vencimiento y observaciones en el pago, propagados a los apuntes contables.",
    "description": """
What it does:
Adds the "Check number", "Due date" and "Notes" fields to the payment register
wizard (account.payment.register), to the payment (account.payment) and to the
journal item (account.move.line). When the payment is confirmed, those values are
carried from the payment to the reconciled journal items, so the check number and
its due date are available at journal item level for reports and queries.

What it is for:
Traceability of checks, post-dated ones above all, from the payment down to the
journal entry. It is the base layer for check wallets, credit control and due date
reports.

Scope:
Generic, multi-company and multi-customer. Depends on account only. It assumes no
particular journal and no particular provider.

Configuration:
None. The fields show up in the payment register wizard and in the payment form.

[ES] Version en espanol:

Qué hace:
Agrega los campos "Número de cheque", "Vencimiento" y "Observaciones" al registro de
pago (account.payment.register), al pago (account.payment) y a la línea de asiento
(account.move.line). Al confirmar el pago, propaga esos datos del pago a las líneas de
asiento conciliadas, de modo que el vencimiento y el número de cheque quedan disponibles
a nivel de apunte contable para reportes y consultas.

Para qué sirve:
Dar trazabilidad de cheques (sobre todo diferidos) desde el pago hasta el asiento, base
para carteras de cheques, control de crédito y reportes de vencimientos.

Alcance:
Genérico multi-cliente. Depende solo de account. No asume ningún diario ni proveedor
específico.

Configuración:
Sin configuración propia. Los campos aparecen en el asistente de registro de pago y en
el formulario de pago.
""",
    "author": "Polpo ERP",
    "website": "https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_cheque_info",
    "support": "info@polpo.uy",
    "category": "Accounting",
    "version": "18.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "views/account_payment_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
