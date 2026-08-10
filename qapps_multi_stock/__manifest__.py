# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

{
    "name": "Multi Depósito: venta inter sucursal",
    "summary": "Venta en sucursal de stock ubicado en otro depósito: traslado "
    "interno con tránsito y doble validación, o envío directo "
    "(drop-ship) desde el depósito central al cliente.",
    "sequence": 160,
    "version": "17.0.1.3.3",
    "category": "Inventory",
    "license": 'LGPL-3',
    "author": "Polpo ERP",
    "website": "https://polpo.uy/?utm_source=odoo_apps&utm_medium=referral&utm_campaign=qapps_multi_stock",
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
    "images": ["static/description/banner.png"],
    "installable": True,
}
