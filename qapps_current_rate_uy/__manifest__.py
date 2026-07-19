# -*- coding: utf-8 -*-
{
    'name': "QApps - Tasa de Cambio Uruguay - BCU",
    'summary': "Importa automáticamente del BCU la cotización diaria de todas las monedas activas (USD, EUR, UYI)",
    'description': """
        Qué hace: una tarea programada (cron) diaria consulta los web services SOAP
        del BCU (awsultimocierre + awsbcucotizaciones, vía zeep) y crea
        res.currency.rate para cada moneda activa, en todas las compañías activas
        (multi-compañía). USD y EUR se cargan como tasa inversa (1/TCC); la Unidad
        Indexada (UYI, código BCU "U.I.") se carga con TCC directo.

        Para qué sirve: mantener los tipos de cambio al día sin carga manual,
        requisito de la operativa bimonetaria UYU/USD uruguaya.

        Alcance: módulo genérico QApps, multi-cliente. No depende de otros
        módulos QApps.

        Configuración (Ajustes): activar/desactivar el cron, URLs de los WSDL
        del BCU y email de notificación si el BCU no devuelve cotización
        (default soporte@qapps.io). Parámetros en ir.config_parameter
        (qapps.currency_*).
    """,
    'sequence': 150,
    'author': "Polpo ERP",
    'website': 'https://polpo.uy',
    'support': 'info@polpo.uy',
    'category': 'Accounting',
    'version': '18.0.1.0.3',
    'depends': ['base'],
    'license': 'LGPL-3',
    'data': [
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
}
