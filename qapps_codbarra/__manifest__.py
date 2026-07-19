{
    "name": "QApps - Código de Barras",
    "summary": "Control de cantidades en traslados de stock mediante lectura de códigos de barras",
    "description": """
Qué hace:
Agrega un control de cantidades por código de barras a los traslados de stock
(stock.picking), sin usar el módulo Barcode de Odoo EE. Incorpora un campo de escaneo en
el albarán y un wizard "Lector de códigos": cada escaneo busca el producto por su código
de barras e incrementa en 1 la cantidad controlada (qty_checked, campo nuevo en
stock.move), validando que el producto pertenezca a la orden y que no se supere la
cantidad demandada. Cuando todas las líneas quedan verificadas (o se marca manualmente
el check "Controlado", que completa todas las cantidades) se registra usuario y fecha
del control.

Para qué sirve:
Verificar físicamente, producto por producto, lo que se recibe o se despacha en depósito,
dejando trazabilidad de quién controló y cuándo.

Alcance:
Genérico multi-cliente. Solo requiere productos con código de barras cargado.

Configuración:
Sin configuración propia. Requiere el campo 'Código de barras' completo en los productos.
""",
    "sequence": 150,
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "category": "Inventory",
    "version": '16.0.1.0.0',
    "license": 'LGPL-3',
    "depends": ["stock"],
    "data": [
        "security/ir.model.access.csv",
        "views/qapps_stock_picking_views.xml",
        "wizard/qapps_barcode_reader_views.xml",
    ],
    "installable": True,
    "application": False,
}
