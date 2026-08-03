# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

{
    "name": "Multi Depósito (venta inter-sucursal) - QApps",
    "summary": "Venta en sucursal de stock ubicado en otro depósito: traslado "
    "interno con tránsito y doble validación, o envío directo "
    "(drop-ship) desde el depósito central al cliente.",
    "sequence": 160,
    "version": "17.0.1.3.0",
    "category": "Inventory",
    "license": 'LGPL-3',
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "depends": [
        "sale_stock",
        "stock",
        ],
    "data": [
        "views/stock_warehouse_views.xml",
        "views/sale_order_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
}
