{
    "name": "Uruguay: Base Fiscal - Polpo",
    "summary": "Tipos de documento DGI, validación de RUT/C.I. y utilidades para localización uruguaya",
    "description": """
Qué hace:
Agrega el campo "Tipo Doc." (clasificación de documentos de la DGI: RUC, C.I.,
pasaporte, DNI regional) y "Razón social" al contacto (res.partner), con validación
automática del dígito verificador de RUT y Cédula de Identidad uruguaya. Expone además
un conjunto de utilidades reutilizables (helpers de texto, fechas en huso de Montevideo,
detección de RUC) usadas por los módulos de facturación electrónica.

Para qué sirve:
Ser la dependencia técnica común de los módulos de documentación fiscal uruguaya, sin
duplicar la lógica de tipos de documento y validación en cada uno.

Alcance:
Genérico multi-cliente para Uruguay. No incluye customizaciones de cliente ni conexión a
proveedores de CFE (eso vive en los módulos de facturación electrónica).

Configuración:
Sin configuración propia.
""",
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "category": "Localization",
    "version": "16.0.1.0.2",
    "license": "LGPL-3",
    "depends": ["base", "contacts"],
    "data": [
        "views/res_partner_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
