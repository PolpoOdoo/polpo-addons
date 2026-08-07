{
    "name": "Cheque Info en Pagos y Apuntes",
    "summary": "Número de cheque, vencimiento y observaciones en el pago, propagados a los apuntes contables",
    "description": """
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
    "website": "https://polpo.uy",
    "category": "Accounting",
    "version": "17.0.1.0.3",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "views/account_payment_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
