# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class StockPicking(models.Model):
    """Trazabilidad de los traslados/drop-ship inter-sucursal con su venta, y
    control para no recibir desde tránsito antes de que el origen despache.

    Además, auto-genera la recepción de reabastecimiento inter-almacén cuando se
    valida un despacho Origen -> Tránsito que corresponde a un mapeo multi
    depósito (ver ``_multi_stock_spawn_reception``). Así el traslado interno
    (pedir mercadería a depósito) se ingresa UNA sola vez —en el despacho— y la
    recepción en el destino es solo validar lo que llega."""

    _inherit = "stock.picking"

    multi_stock_sale_id = fields.Many2one(
        "sale.order",
        string="Venta (multi depósito)",
        copy=False,
        index=True,
        help="Pedido de venta que originó este traslado o envío directo "
        "inter-sucursal (rutas R2 / R3 de multi depósito).",
    )
    multi_stock_dispatch_id = fields.Many2one(
        "stock.picking",
        string="Despacho de traslado (multi depósito)",
        copy=False,
        index=True,
        help="Despacho Origen -> Tránsito que generó esta recepción de "
        "reabastecimiento inter-almacén. Permite controlar la recepción contra "
        "lo despachado.",
    )

    def button_validate(self):
        # Se valida ANTES del super(). El asistente de transferencia inmediata
        # vuelve a llamar a button_validate con las cantidades ya seteadas, así
        # que ese camino también queda cubierto.
        self._multi_stock_check_transit_disponible()
        return super().button_validate()

    def _action_done(self):
        # Al completarse el despacho (moves en 'done', cantidades reales
        # conocidas) se genera la recepción del destino. Se engancha en
        # _action_done y no en button_validate porque este último puede devolver
        # un asistente (backorder/transferencia inmediata) sin haber completado
        # todavía; _action_done corre cuando el picking realmente se cierra.
        res = super()._action_done()
        self._multi_stock_spawn_reception()
        return res

    def _multi_stock_check_transit_disponible(self):
        """Bloquea validar la recepción de un traslado inter-almacén
        (Tránsito -> Destino) si la ubicación de tránsito no tiene stock físico
        suficiente, es decir, si todavía no se validó el despacho del origen.
        Evita el stock negativo en tránsito."""
        for picking in self:
            # Recepciones de multi depósito: las del flujo de venta
            # (multi_stock_sale_id) y las de reabastecimiento manual
            # (multi_stock_dispatch_id).
            if not (picking.multi_stock_sale_id or picking.multi_stock_dispatch_id):
                continue
            # Solo las recepciones desde tránsito (no el despacho ni el drop-ship).
            if picking.location_id.usage != "transit":
                continue
            transit = picking.location_id
            for move in picking.move_ids:
                if move.state in ("done", "cancel"):
                    continue
                uom = move.product_id.uom_id
                qty = move.product_uom._compute_quantity(move.quantity, uom)
                if float_is_zero(qty, precision_rounding=uom.rounding):
                    continue
                disponible = move.product_id.with_context(
                    location=transit.id
                ).qty_available
                if float_compare(qty, disponible, precision_rounding=uom.rounding) > 0:
                    raise UserError(
                        _(
                            "No se puede validar la recepción %(picking)s: la "
                            "ubicación de tránsito no tiene stock suficiente de "
                            "%(prod)s (disponible %(disp)s, a recibir %(qty)s). "
                            "Primero validá el despacho del origen hacia el tránsito."
                        )
                        % {
                            "picking": picking.name,
                            "prod": move.product_id.display_name,
                            "disp": disponible,
                            "qty": qty,
                        }
                    )

    def _multi_stock_spawn_reception(self):
        """Al validar un despacho Origen -> Tránsito que corresponde a un mapeo
        de reabastecimiento (``stock.warehouse`` destino con
        ``multi_stock_transit_location_id``), genera la recepción
        Tránsito -> Destino precargada con lo efectivamente despachado y
        pendiente de validar.

        El despacho NO se cablea a nada: el match es por ubicaciones (tránsito
        del mapeo + origen dentro del almacén de reabastecimiento), así sirve
        tanto para el traslado manual (pedir a depósito) como para cualquier
        despacho a ese tránsito. Los despachos del flujo de venta ya traen su
        recepción creada por código (vinculada con ``multi_stock_dispatch_id``)
        y se saltean para no duplicarla.

        Se crea con sudo: quien valida el despacho es un usuario del origen que
        puede no tener acceso a la compañía del destino (mismo criterio que el
        resto del módulo)."""
        Warehouse = self.env["stock.warehouse"].sudo()
        Picking = self.env["stock.picking"].sudo()
        # Almacenes con mapeo de reabastecimiento cargado (en EI: uno).
        mapeados = Warehouse.search([("multi_stock_transit_location_id", "!=", False)])
        if not mapeados:
            return
        for picking in self:
            if picking.location_dest_id.usage != "transit":
                continue
            transit = picking.location_dest_id
            # Almacén destino cuyo tránsito es este y cuyo origen contiene la
            # ubicación de salida del despacho (child_of vía parent_path).
            dest_wh = mapeados.filtered(
                # transit/picking se bindean como defaults (evalúa en el acto,
                # pero evita el warning B023 de captura de variable de loop).
                lambda w,
                transit=transit,
                picking=picking: w.multi_stock_transit_location_id == transit
                and w.multi_stock_in_type_id
                and w.multi_stock_source_warehouse_id
                and picking.location_id.parent_path.startswith(
                    w.multi_stock_source_warehouse_id.view_location_id.parent_path
                )
            )[:1]
            if not dest_wh:
                continue
            # ¿El despacho ya tiene su recepción (flujo de venta u otra pasada)?
            if Picking.search_count([("multi_stock_dispatch_id", "=", picking.id)]):
                continue
            dest_loc = dest_wh.lot_stock_id
            move_vals = []
            for move in picking.move_ids:
                if move.state != "done":
                    continue
                if float_is_zero(
                    move.quantity, precision_rounding=move.product_uom.rounding
                ):
                    continue
                move_vals.append(
                    (
                        0,
                        0,
                        {
                            "name": move.product_id.display_name,
                            "product_id": move.product_id.id,
                            "product_uom_qty": move.quantity,
                            "product_uom": move.product_uom.id,
                            "location_id": transit.id,
                            "location_dest_id": dest_loc.id,
                            "company_id": dest_wh.company_id.id,
                            "procure_method": "make_to_stock",
                        },
                    )
                )
            if not move_vals:
                continue
            reception = Picking.create(
                {
                    "picking_type_id": dest_wh.multi_stock_in_type_id.id,
                    "company_id": dest_wh.company_id.id,
                    "location_id": transit.id,
                    "location_dest_id": dest_loc.id,
                    "origin": picking.origin or picking.name,
                    "partner_id": picking.partner_id.id,
                    "multi_stock_dispatch_id": picking.id,
                    "move_ids": move_vals,
                }
            )
            reception.action_confirm()
            # Reserva desde el tránsito, que ya tiene físicamente lo despachado.
            reception.action_assign()
