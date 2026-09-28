# -*- coding: utf-8 -*-
{
    'name': "Uruguay BCU Exchange Rates / Cotizaciones BCU Uruguay",
    'summary': "Daily automatic import of the Central Bank of Uruguay rates for every active currency (USD, EUR, UI). / Importa todos los días del BCU la cotización de las monedas activas (USD, EUR, UI).",
    'description': """
        What it does: a daily scheduled action queries the SOAP web services of
        the Central Bank of Uruguay (awsultimocierre + awsbcucotizaciones,
        through zeep) and creates a res.currency.rate for every active currency,
        in every active company (multi-company). Every currency is stored with
        the standard Odoo semantics: the BCU publishes the rate as pesos per
        unit of currency, so the module saves its inverse (1/TCC), which is
        what res.currency.rate expects. That includes the Indexed Unit (UYI,
        BCU code "U.I.").

        What it is for: keeping exchange rates up to date without manual entry,
        a requirement of the bimonetary UYU/USD operation in Uruguay.

        Scope: generic, multi-company and multi-customer. It depends on no other
        module of ours.

        Configuration (Settings): turn the scheduled action on or off, the URLs
        of the BCU WSDL services, and the notification email used when the BCU
        returns no rate (info@polpo.uy by default). The values are stored in
        ir.config_parameter (qapps.currency_*).

        Requirements: the zeep Python library (pip install zeep).

        [ES] Version en espanol:

        Qué hace: una tarea programada (cron) diaria consulta los web services SOAP
        del BCU (awsultimocierre + awsbcucotizaciones, vía zeep) y crea
        res.currency.rate para cada moneda activa, en todas las compañías activas
        (multi-compañía). Todas las monedas se guardan con la semántica estándar
        de Odoo: el BCU publica la cotización en pesos por unidad de la moneda,
        así que el módulo guarda su inversa (1/TCC), que es lo que espera
        res.currency.rate. Incluye la Unidad Indexada (UYI, código BCU "U.I.").

        Para qué sirve: mantener los tipos de cambio al día sin carga manual,
        requisito de la operativa bimonetaria UYU/USD uruguaya.

        Alcance: módulo genérico QApps, multi-cliente. No depende de otros
        módulos QApps.

        Configuración (Ajustes): activar/desactivar el cron, URLs de los WSDL
        del BCU y email de notificación si el BCU no devuelve cotización
        (default info@polpo.uy). Parámetros en ir.config_parameter
        (qapps.currency_*).

        Requisitos: la librería Python zeep (pip install zeep).
    """,
    'sequence': 150,
    'author': "Polpo ERP",
    'website': 'https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_currency_rate_bcu',
    'support': 'info@polpo.uy',
    'category': 'Accounting',
    'version': '18.0.1.0.1',
    'depends': ['base', 'mail'],
    'external_dependencies': {'python': ['zeep']},
    'license': 'LGPL-3',
    'data': [
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
}
