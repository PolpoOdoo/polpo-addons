{
    "name": "Cheques en Cartera",
    "summary": "Cartera de cheques recibidos: consulta unificada, depósito, endoso a proveedores y envío al cobro",
    "description": """
        Qué hace: agrega la vista de consulta "Cheques en cartera" (modelo SQL
        qapps.check.wallet, con dashboard) que muestra cada cheque recibido y su
        ciclo de vida completo: Pendiente -> En boleta / Depositado (vía
        account_check_deposit OCA) -> o En endoso / Endosado
        (qapps.check.endorsement: endoso a proveedor con conciliación de sus
        facturas) -> o Enviado al cobro / Al cobro / Acreditado / Rechazado
        (qapps.check.collection: entrega al banco con cuentas puente por moneda,
        resolución por cheque individual). Marca diarios como "de cheques"
        (is_check_journal) y notifica por cron los vencimientos del día.

        Para qué sirve: tesorería con cheques diferidos, práctica habitual en
        Uruguay: saber qué cheques hay en cartera, cuándo vencen y qué se hizo
        con cada uno.

        Alcance: módulo genérico QApps, multi-cliente. Depende de
        account_check_deposit (OCA) y qapps_cheque_info.
    """,
    "sequence": 150,
    "version": "17.0.1.3.15",
    "category": "Accounting",
    "license": 'AGPL-3',
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "depends": [
        "account_check_deposit",
        "qapps_cheque_info",
    ],
    "data": [
        "security/qapps_check_wallet_security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/account_journal_views.xml",
        "views/qapps_check_wallet_views.xml",
        "views/account_check_deposit_views.xml",
        "views/qapps_check_endorsement_views.xml",
        "views/qapps_check_collection_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "qapps_check_wallet/static/src/views/check_wallet_list_controller.js",
            "qapps_check_wallet/static/src/views/check_wallet_list_controller.xml",
            "qapps_check_wallet/static/src/views/check_wallet_list_view.js",
            "qapps_check_wallet/static/src/views/check_wallet_dashboard.scss",
        ],
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
