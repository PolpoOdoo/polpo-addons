# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class StockWarehouse(models.Model):
    """Mapeo de reabastecimiento inter-almacén (parametrizable).

    Se configura en el almacén que vende sin tener el stock (el almacén DESTINO).
    Indica de qué almacén ORIGEN se trae la mercadería, por qué ubicación de
    tránsito (compartida, ``company_id = False``) y con qué tipos de operación se
    generan los pickings de las rutas R2 (vía almacén destino) y R3 (envío
    directo / drop-ship desde el origen al cliente).

    El mapeo es por almacén y direccional: para habilitar el caso inverso
    (que el origen también pueda venderse trayendo stock del otro), se completa
    el mismo bloque en el otro almacén apuntando a su propio origen.

    Es configuración por almacén, NO por producto. La decisión de qué ruta usar
    se toma en runtime según el stock cargado (ver ``sale.order.line``).
    """

    _inherit = "stock.warehouse"

    multi_stock_source_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Almacén de reabastecimiento (origen)",
        help="Almacén ORIGEN del que se trae el stock cuando este almacén no lo "
        "tiene. Completar este campo es lo que habilita el multi depósito "
        "para las ventas de este almacén.",
    )
    multi_stock_transit_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación de tránsito",
        domain="[('usage', '=', 'transit')]",
        help="Ubicación de tránsito compartida entre el almacén origen y este "
        "almacén. DEBE tener company_id = False para que ambas compañías "
        "operen sobre ella.",
    )
    multi_stock_out_type_id = fields.Many2one(
        "stock.picking.type",
        string="Tipo op. despacho (origen -> tránsito)",
        help="Tipo de operación, en la compañía del almacén ORIGEN, para el "
        "despacho Origen/Existencias -> Tránsito (R2). Lo valida un usuario "
        "del origen.",
    )
    multi_stock_in_type_id = fields.Many2one(
        "stock.picking.type",
        string="Tipo op. recepción (tránsito -> destino)",
        help="Tipo de operación, en este almacén, para la recepción "
        "Tránsito -> Destino/Existencias (R2). Lo valida un usuario de este "
        "almacén.",
    )
    multi_stock_dropship_type_id = fields.Many2one(
        "stock.picking.type",
        string="Tipo op. envío directo (origen -> cliente)",
        help="Tipo de operación, en la compañía del almacén ORIGEN, para el "
        "drop-ship Origen/Existencias -> Cliente (R3). Lo valida/reparte un "
        "usuario del origen.",
    )
    multi_stock_solo_reabastecimiento = fields.Boolean(
        string="Solo reabastecimiento interno",
        help="Si está activo, este almacén participa SOLO del reabastecimiento "
        "inter-almacén: al validar un despacho hacia el tránsito se auto-genera "
        "la recepción en este almacén (SPEC 4.6). NO interviene la venta: una "
        "venta desde este almacén con faltante sigue el flujo nativo de Odoo "
        "(sin exigir el selector de cumplimiento ni generar traslado/drop-ship "
        "automáticos). Es el caso de un almacén que vende con su propio stock "
        "pero se abastece de otro por traslado manual.",
    )
