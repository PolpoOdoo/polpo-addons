{
    "name": "Retenciones en Garantía y CCE",
    "summary": "Retenciones en garantía y Certificados de Crédito fiscal (CCE) sobre facturas de cliente",
    "description": """
Qué hace:
Agrega a las facturas de cliente el modelo qapps.retenciones.cce, con dos tipos de
aplicación: "Retención en garantía" (porcentaje sobre el total o la base imponible de la
factura, opcionalmente limitado a líneas específicas) y "Certificado de crédito fiscal"
(por el monto de IVA de la factura). Al postear la factura genera automáticamente un
asiento de reclasificación que mueve el monto retenido de la cuenta a cobrar a la cuenta
configurada por tipo, y lo reconcilia contra el receivable (con soporte multimoneda:
amount_currency al tipo de cambio de la factura y reparto del centavo de redondeo entre
retenciones). La regularización se hace desde el pago: campos "Tipo de aplicación" y
"Aplicación a regularizar" en account.payment redirigen la cuenta destino a la cuenta de
retenciones/CCE y, al confirmar, marcan la retención como Cobrada con fecha y pago
asociado. Sincroniza la referencia del asiento cuando qapps_efactura renombra la factura
con el número de CFE.

Para qué sirve:
Rubros donde el cliente retiene parte de la factura: construcción/obras (retención en
garantía que se cobra al finalizar la obra) y organismos que pagan el IVA con certificados
de crédito fiscal. Mantiene el saldo exigible de la factura correcto y da seguimiento a lo
retenido hasta su cobro, con imputación analítica por Proyecto/Obra.

Alcance:
Genérico multi-cliente (depende solo de account). Contempla facturación en moneda extranjera (USD).

Configuración e integraciones:
En Ajustes de Contabilidad: "Cuenta Retenciones en garantía" y "Cuenta certificados de
crédito fiscal" por compañía. Compatible con qapps_efactura (no lo requiere).
    """,
    "sequence": 150,
    "author": "Polpo ERP",
    "website": "https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_retenciones_cce",
    "support": "info@polpo.uy",
    "category": "Accounting",
    "version": "18.0.1.0.4",
    "license": 'LGPL-3',
    "depends": [
        "account",
    ],
    "data": [
        "security/qapps_retenciones_cce_security.xml",
        "security/ir.model.access.csv",
        "views/account_move_views.xml",
        "views/account_payment_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
}
