{
    "name": "Control de Traslados por Código de Barras - Polpo",
    "summary": "Control de cantidades en traslados de stock mediante lectura de códigos de barras",
    "description": """
Qué hace:
Agrega un control de cantidades por código de barras a los traslados de stock
(stock.picking), sin usar el módulo Barcode de Odoo EE. Incorpora un campo de escaneo en
el albarán y un wizard "Lector de códigos": cada escaneo busca el producto por su código
de barras e incrementa en 1 la cantidad controlada (qty_checked, campo nuevo en
stock.move), validando que el producto pertenezca a la orden y que no se supere la
cantidad demandada. Cuando todas las líneas quedan verificadas (o se marca manualmente
el check "Controlado", que completa todas las cantidades) se registra usuario y fecha del
control y se deja una nota en el chatter. Además, al confirmar una orden de compra pone
en 0 las cantidades hechas de los movimientos de recepción, para forzar que el conteo se
haga escaneando (o cargando cantidades reales) en lugar de aceptar las cantidades
precompletadas por Odoo.

Para qué sirve:
Verificar físicamente, producto por producto, lo que se recibe o se despacha en depósito,
dejando trazabilidad de quién controló y cuándo, y evitando validar recepciones con las
cantidades sugeridas sin conteo real.

Alcance:
Genérico multi-cliente. Solo requiere productos con código de barras cargado.

Configuración:
Sin configuración propia. Requiere el campo 'Código de barras' completo en los productos.
""",
    "sequence": 150,
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "category": "Inventory",
    "version": "17.0.1.0.5",
    "license": 'LGPL-3',
    "depends": [
        "stock",
        "purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/qapps_stock_picking_views.xml",
        "wizard/qapps_barcode_reader_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
