# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

{
    "name": "Multi-Warehouse Inter-Branch Sales / Multi Depósito: venta inter sucursal",
    "summary": "Sell at a branch stock located in another warehouse: internal "
    "transfer with transit and double validation, or direct delivery "
    "(drop-ship) from the source warehouse to the customer. / Venta en "
    "sucursal de stock ubicado en otro depósito.",
    "description": """
What it does:
Lets a branch sell stock that is physically in another warehouse. On confirming the
order, each line with a local shortage is routed through one of three paths: deliver
what is available locally, move the shortage by an internal transfer through a
transit location with double validation (dispatch at the source, receipt at the
destination), or drop-ship the shortage from the source warehouse straight to the
customer. The salesperson sees the available and the missing quantity on the order
line and has to choose how to fulfil the shortage before confirming. Cancelling the
sale cascades to the pending transfers and drop-ships it generated; the ones
already validated are left for manual handling. The order also shows the documents
the source warehouse generated, even when the source is another company, and
refuses to emit a second remittance for a sale that was already dispatched.

What it is for:
Selling at the counter without depending on where the goods physically are, and
without resolving inter-branch sales by phone and a hand-written remittance.

Scope:
Generic, multi-company and multi-customer. It depends only on standard Sales and
Inventory. The routing is configured per warehouse, not per product, and it is
directional: the same mechanism works in both directions depending on which
warehouse carries the mapping.

Configuration:
On the warehouse that sells without holding the stock, set the source warehouse,
the shared transit location and the operation types used for the dispatch, the
receipt and the drop-ship.

[ES] Version en espanol:

Qué hace:
Permite vender en una sucursal el stock que está físicamente en otro depósito. Al
confirmar el pedido, cada línea con faltante local se resuelve por uno de tres
caminos: entregar lo disponible en el almacén de la venta, traer el faltante por un
traslado interno con ubicación de tránsito y doble validación (despacho en el
origen, recepción en el destino), o enviar el faltante directo desde el depósito de
origen al cliente. El vendedor ve en la línea lo disponible y lo que falta, y tiene
que elegir cómo cumplir el faltante antes de confirmar. Cancelar la venta cancela
en cascada los traslados y envíos directos pendientes que había generado; los ya
validados quedan para gestionarlos a mano. El pedido además muestra los documentos
que generó el depósito de origen, incluso cuando el origen es otra compañía, y no
deja emitir un segundo remito por una venta ya despachada.

Para qué sirve:
Vender en el mostrador sin depender de dónde está físicamente la mercadería, y sin
resolver la venta entre sucursales por teléfono y remito manual.

Alcance:
Genérico multi-compañía y multi-cliente. Depende solo de los módulos estándar de
Ventas e Inventario. La configuración es por almacén, no por producto, y es
direccional: el mismo mecanismo sirve en los dos sentidos según qué almacén tenga
el mapeo cargado.

Configuración:
En el almacén que vende sin tener el stock se carga el depósito de origen, la
ubicación de tránsito compartida y los tipos de operación que se usan para el
despacho, la recepción y el envío directo.
""",
    "sequence": 160,
    "version": "18.0.1.0.0",
    "category": "Inventory",
    "license": "LGPL-3",
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
