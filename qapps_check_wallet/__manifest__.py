{
    'name': 'Post-dated Check Wallet / Cheques en Cartera',
    'summary': 'Received checks in one place: wallet, bank deposit, endorsement to vendors and collection, with daily due-date alerts. / Cartera de cheques recibidos: depósito, endoso a proveedores, envío al cobro y aviso diario de vencimientos.',
    'description': """
        What it does: adds the "Checks in wallet" query view (SQL model
        qapps.check.wallet, with a dashboard) that shows every received check and
        its whole life cycle: Pending -> In deposit slip / Deposited (through
        account_check_deposit, OCA) -> or In endorsement / Endorsed
        (qapps.check.endorsement: endorsement to a vendor, reconciling their
        bills) -> or Sent to collection / At collection / Credited / Rejected
        (qapps.check.collection: handover to the bank with bridge accounts per
        currency, resolved check by check). Flags journals as check journals
        (is_check_journal) and notifies the checks falling due today by cron.

        What it is for: treasury with post-dated checks, common practice in
        Uruguay and across the region: knowing which checks are in the wallet,
        when they fall due and what was done with each one.

        Scope: generic, multi-company and multi-customer. Depends on
        account_check_deposit (OCA) and qapps_cheque_info.

        [ES] Version en espanol:

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
    'sequence': 150,
    'version': '18.0.1.3.14',
    'category': 'Accounting',
    'license': 'AGPL-3',
    'author': 'Polpo ERP',
    'website': 'https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_check_wallet',
    'support': 'info@polpo.uy',
    'depends': [
        'account_check_deposit',
        'qapps_cheque_info',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/qapps_check_wallet_security.xml',
        'data/sequence.xml',
        'data/cron.xml',
        'views/account_journal_views.xml',
        'views/qapps_check_wallet_views.xml',
        'views/account_check_deposit_views.xml',
        'views/qapps_check_endorsement_views.xml',
        'views/qapps_check_collection_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'qapps_check_wallet/static/src/views/check_wallet_list_controller.js',
            'qapps_check_wallet/static/src/views/check_wallet_list_controller.xml',
            'qapps_check_wallet/static/src/views/check_wallet_list_view.js',
            'qapps_check_wallet/static/src/views/check_wallet_dashboard.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
}
