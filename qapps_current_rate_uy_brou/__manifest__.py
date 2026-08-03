{
    "name": "Cotizaciones BROU Uruguay - Polpo",
    "summary": "Importa automáticamente del sitio del BROU las tasas de compra y venta del dólar (monedas DOC y DOL)",
    "description": """
        Qué hace: un cron diario scrapea la tabla de cotizaciones del sitio web del
        BROU (requests + BeautifulSoup, sin API oficial) y crea res.currency.rate
        en todas las compañías activas: tasa de VENTA en la moneda DOL y tasa de
        COMPRA en la moneda DOC (monedas ficticias que el cliente debe tener
        creadas). No pisa tasas ya cargadas para la fecha.

        Para qué sirve: clientes que operan con tasa BROU (billete) en lugar de la
        interbancaria del BCU. Complementa a qapps_current_rate_uy.

        Alcance: módulo genérico QApps, multi-cliente.

        Configuración (Ajustes): booleano que activa/desactiva el cron
        (ir.config_parameter brou.currency_update).
    """,
    "sequence": 150,
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "category": "Accounting",
    "version": "17.0.1.0.6",
    "depends": ["base", "account"],
    "license": 'LGPL-3',
    "data": [
        "security/ir.model.access.csv",
        # 'views/brou_currency_rate_views.xml',
        "views/res_config_settings_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
}
