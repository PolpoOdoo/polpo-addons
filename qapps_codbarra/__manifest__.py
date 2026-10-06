{
    "name": "Barcode Transfer Check / Control de Traslados por Código de Barras",
    "summary": "Quantity control on stock transfers by scanning barcodes, without the Enterprise Barcode module. / Control de cantidades en traslados de stock mediante lectura de códigos de barras.",
    "description": """
What it does:
Adds a barcode quantity control to stock transfers (stock.picking) without using
the Odoo Enterprise Barcode module. It puts a scanning field on the transfer and a
"Barcode reader" wizard: every scan looks the product up by its barcode and adds 1
to the checked quantity (qty_checked, a new field on stock.move), validating that
the product belongs to the transfer and that the demanded quantity is not
exceeded. Once every line is verified (or the "Checked" flag is ticked by hand,
which completes all the quantities) the module records who checked it and when,
and leaves a note in the chatter. On top of that, confirming a purchase order sets
the done quantities of the receipt moves to zero, so the count has to be made by
scanning (or by entering real quantities) instead of accepting the quantities Odoo
pre-fills.

What it is for:
Physically verifying, product by product, what is received or dispatched at the
warehouse, leaving a trace of who checked it and when, and avoiding receipts
validated with suggested quantities and no real count.

Scope:
Generic and multi-customer. It only requires products with their barcode filled in.

Configuration:
None. It requires the 'Barcode' field filled in on the products.

[ES] Version en espanol:

Qué hace:
Agrega un control de cantidades por código de barras a los traslados de stock
(stock.picking), sin usar el módulo Barcode de Odoo Enterprise. Incorpora un campo
de escaneo en el traslado y un asistente "Lector de códigos": cada escaneo busca el
producto por su código de barras e incrementa en 1 la cantidad controlada
(qty_checked, campo nuevo en stock.move), validando que el producto pertenezca a la
orden y que no se supere la cantidad demandada. Cuando todas las líneas quedan
verificadas (o se marca manualmente el check "Controlado", que completa todas las
cantidades) se registra usuario y fecha del control y se deja una nota en el
chatter. Además, al confirmar una orden de compra pone en 0 las cantidades hechas
de los movimientos de recepción, para forzar que el conteo se haga escaneando (o
cargando cantidades reales) en lugar de aceptar las cantidades precompletadas por
Odoo.

Para qué sirve:
Verificar físicamente, producto por producto, lo que se recibe o se despacha en
depósito, dejando trazabilidad de quién controló y cuándo, y evitando validar
recepciones con las cantidades sugeridas sin conteo real.

Alcance:
Genérico multi-cliente. Solo requiere productos con código de barras cargado.

Configuración:
Sin configuración propia. Requiere el campo 'Código de barras' completo en los
productos.
""",
    "sequence": 150,
    "author": "Polpo ERP",
    "website": "https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_codbarra",
    "support": "info@polpo.uy",
    "category": "Inventory",
    "version": "18.0.1.0.1",
    "license": "LGPL-3",
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
