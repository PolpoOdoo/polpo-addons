{
    "name": "Autocompletado de Direcciones Uruguay",
    "summary": "Sesga el autocompletado de direcciones de la tienda hacia Uruguay",
    "description": """
        Qué hace: override del controller de website_sale_autocomplete. Cuando la
        búsqueda de direcciones de Google no trae país ni idioma, aplica por
        defecto país Uruguay (components=country:UY) e idioma es-419, en vez de
        dejar la búsqueda sin sesgo geográfico/idiomático.

        Para qué sirve: mejora el autocompletado de direcciones en el checkout de
        la tienda para clientes uruguayos.

        Origen: reintroduce como override una customización de core que se perdía
        en cada actualización de Odoo desde upstream (commit 8766ecd10
        "Ajusto google search", que patcheaba directamente
        website_sale_autocomplete/controllers/main.py).
    """,
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "category": "Website/eCommerce",
    "version": "17.0.1.0.3",
    "depends": ["website_sale_autocomplete"],
    "license": 'LGPL-3',
    "images": ["static/description/banner.png"],
    "installable": True,
}
