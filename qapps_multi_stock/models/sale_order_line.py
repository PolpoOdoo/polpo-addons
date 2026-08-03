# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models
from odoo.tools import float_is_zero

MULTI_STOCK_MODE = [
    ("retira_despues", "Retira/entrega luego (vía almacén destino)"),
    ("envio_directo", "Envío directo desde el origen"),
    ("solo_existente", "Se entrega lo existente"),
]


class SaleOrderLine(models.Model):
    """Disponibilidad local y modo de cumplimiento por línea.

    La disponibilidad se mide con ``free_qty`` (físico - reservado) en el
    depósito del almacén donde se hace la venta (DESTINO). Lo reservado NO cuenta
    como disponible.

    El selector ``multi_stock_mode`` SOLO aplica/es visible cuando la línea tiene
    faltante local Y el almacén de la venta está habilitado para multi depósito
    (tiene ``multi_stock_source_warehouse_id`` y NO está en modo
    ``multi_stock_solo_reabastecimiento``). La cantidad disponible local se
    entrega siempre por R1 (inmediata), salvo override ``multi_stock_todo_origen``.
    """

    _inherit = "sale.order.line"

    multi_stock_free_local = fields.Float(
        string="Disponible en este almacén",
        compute="_compute_multi_stock_disponibilidad",
        digits="Product Unit of Measure",
        help="free_qty del producto en el depósito del almacén de la venta.",
    )
    multi_stock_faltante = fields.Float(
        string="Faltante en este almacén",
        compute="_compute_multi_stock_disponibilidad",
        digits="Product Unit of Measure",
    )
    multi_stock_tiene_faltante = fields.Boolean(
        string="Tiene faltante",
        compute="_compute_multi_stock_disponibilidad",
    )
    multi_stock_mode = fields.Selection(
        selection=MULTI_STOCK_MODE,
        string="Cumplimiento del faltante",
        copy=False,
        help="Cómo se cumple la cantidad faltante: traer al almacén destino (R2) "
        "o envío directo desde el origen al cliente (R3). Sólo aplica si hay "
        "faltante.",
    )
    multi_stock_todo_origen = fields.Boolean(
        string="Toda la línea desde el origen",
        copy=False,
        help="Si está activo, toda la cantidad de la línea se cumple desde el "
        "almacén origen (no solo el faltante).",
    )

    @api.depends(
        "product_id",
        "product_uom",
        "product_uom_qty",
        "order_id.warehouse_id",
        "order_id.warehouse_id.multi_stock_source_warehouse_id",
        "order_id.warehouse_id.multi_stock_solo_reabastecimiento",
        "order_id.state",
    )
    def _compute_multi_stock_disponibilidad(self):
        """Disponibilidad local por línea (ver SPEC 4.1).

        Mide ``free_qty`` (físico - reservado, NO ``qty_available``) en el
        depósito del almacén de la venta. Solo aplica a productos almacenables;
        servicios/consumibles -> free=0, sin faltante. ``free_qty`` viene en la
        UoM del producto y se convierte a la UoM de la línea para comparar contra
        la cantidad pedida. El faltante solo habilita el selector si el almacén
        está mapeado para multi depósito (``multi_stock_source_warehouse_id``).
        """
        for line in self:
            free = 0.0
            faltante = 0.0
            tiene_faltante = False
            product = line.product_id
            wh = line.order_id.warehouse_id
            uom = line.product_uom or (product.uom_id if product else False)
            if product and product.type == "product" and wh and wh.lot_stock_id:
                free_product_uom = product.with_context(
                    warehouse=wh.id,
                    location=wh.lot_stock_id.id,
                ).free_qty
                if line.product_uom and line.product_uom != product.uom_id:
                    free = product.uom_id._compute_quantity(
                        free_product_uom, line.product_uom
                    )
                else:
                    free = free_product_uom
                faltante = max(line.product_uom_qty - free, 0.0)
                rounding = uom.rounding if uom else 0.01
                # En modo "solo reabastecimiento" el almacén no interviene la
                # venta: no hay selector de cumplimiento aunque haya faltante.
                tiene_faltante = (
                    bool(wh.multi_stock_source_warehouse_id)
                    and not wh.multi_stock_solo_reabastecimiento
                    and not float_is_zero(faltante, precision_rounding=rounding)
                )
            line.multi_stock_free_local = free
            line.multi_stock_faltante = faltante
            line.multi_stock_tiene_faltante = tiene_faltante
