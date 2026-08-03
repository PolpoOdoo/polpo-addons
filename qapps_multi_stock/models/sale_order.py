# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from markupsafe import Markup, escape

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class SaleOrder(models.Model):
    """Motor de venta multi-depósito (parametrizable y direccional).

    Tras confirmar la venta (super() crea la entrega al cliente vía sale_stock),
    se evalua cada línea con faltante en el almacén de la venta (DESTINO) y se
    generan los documentos de stock según la ruta elegida:
      R1  disponible local -> entrega inmediata (flujo nativo).
      R2  retira_despues -> Origen/Existencias -> Tránsito -> Destino/Existencias.
                            La porción disponible se entrega de inmediato y el
                            SALDO queda en un picking separado, encadenado (MTO)
                            a la recepción (doble validación manual).
      R3  envio_directo  -> drop-ship Origen/Existencias -> Cliente
                            (cross-company); se suprime la entrega del destino
                            por esa cantidad.

    El "faltante" se mide por lo realmente reservado en el destino (no por el
    campo, que en el confirm ya recomputó contra la reserva propia de la venta).

    El "origen" sale del mapeo ``warehouse.multi_stock_source_warehouse_id``; no
    está cableado a un almacén concreto, así que el mismo mecanismo sirve en
    ambos sentidos según qué almacén tenga el mapeo cargado.

    Ver SPEC seccion 4. El auto-validate (envio_automatico / venta_directa) vive
    en los módulos polpo y usa ``_multi_stock_picking_auto_validable`` para
    decidir, sin forzar cantidades. Los pickings inter-almacén (R2
    despacho/recepción + saldo diferido, R3 drop-ship) NUNCA son auto-validables
    de origen: los valida manualmente el usuario de cada compañía.
    """

    _inherit = "sale.order"

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def action_confirm(self):
        res = super().action_confirm()
        # Solo aplicar multi depósito a las órdenes que efectivamente se
        # confirmaron. Otros módulos (ej. sale_financial_risk / riesgo
        # crediticio) interceptan action_confirm devolviendo un wizard SIN
        # llamar a super(): la orden queda en borrador y sin movimientos de
        # stock. Medir el faltante en ese estado da siempre "reservado 0" →
        # UserError "faltan X" con la cantidad completa, y el rollback además
        # se traga el wizard del interceptor.
        for order in self:
            if order.state in ("sale", "done"):
                order._multi_stock_apply()
        return res

    def _action_cancel(self):
        # Se extiende _action_cancel (no action_cancel): el core indica que las
        # operaciones post-cancelación se cuelguen acá, así corre tanto en el
        # cancel directo como después de confirmar el wizard de cancelación.
        res = super()._action_cancel()
        self._multi_stock_cancel_pickings()
        return res

    def _multi_stock_cancel_pickings(self):
        """Cancela los traslados/drop-ship inter-sucursal (R2/R3) que generó el
        multi depósito al cancelarse la venta. El core solo cancela los pickings
        atados al grupo de aprovisionamiento de la venta; los inter-almacén se
        crean en otra compañía y sin ese grupo (los vincula multi_stock_sale_id),
        así que sin esto quedaban ABIERTOS y huérfanos. Solo se cancelan los
        pendientes: los ya validados (mercadería físicamente movida) se dejan
        como están para que el usuario los gestione manualmente."""
        pickings = (
            self.env["stock.picking"]
            .sudo()
            .search(
                [
                    ("multi_stock_sale_id", "in", self.ids),
                    ("state", "not in", ("done", "cancel")),
                ]
            )
        )
        if pickings:
            pickings.action_cancel()

    def _multi_stock_apply(self):
        """Genera los traslados/drop-ship por el FALTANTE real y ajusta la
        entrega al cliente (entrega lo disponible ahora, difiere el saldo). Ver
        SPEC 4.2."""
        self.ensure_one()
        wh = self.warehouse_id
        if not wh or not wh.multi_stock_source_warehouse_id:
            # Almacén sin mapeo multi-depósito -> comportamiento estándar.
            return
        if wh.multi_stock_solo_reabastecimiento:
            # Almacén configurado SOLO para reabastecimiento interno: el mapeo
            # habilita la recepción auto-generada al validar el despacho (SPEC
            # 4.6, en stock.picking) pero NO interviene la venta. La venta con
            # faltante sigue el flujo nativo de Odoo (backorder estándar), sin
            # exigir el selector de cumplimiento ni generar traslado/drop-ship.
            return

        avisos = []
        for line in self.order_line:
            if line.display_type or not line.product_id:
                continue
            if line.product_id.type != "product":
                continue

            qty_total = line.product_uom_qty
            rounding = line.product_uom.rounding

            # Una línea de cantidad <= 0 (devolución del mostrador / NC) no genera
            # traslado ni dropship inter-sucursal: el multi depósito solo cumple
            # FALTANTES de venta, no devoluciones.
            if float_compare(qty_total, 0.0, precision_rounding=rounding) <= 0:
                continue

            # Reservar lo disponible localmente y medir el faltante REAL por lo
            # efectivamente reservado (no por el campo multi_stock_faltante, que
            # en este punto ya recomputó contra la reserva propia de la venta).
            delivery_moves = self._multi_stock_delivery_moves(line)
            delivery_moves._action_assign()
            # La reserva de cada move de entrega está en la UoM del move (la de
            # referencia del producto); qty_total/qty_origen están en la UoM de
            # la LÍNEA, que puede ser secundaria (ej. docenas). Se convierte la
            # reserva a la UoM de la línea para no mezclar unidades al medir el
            # faltante. Con UoM de línea == UoM del producto la conversión es
            # identidad (caso normal, sin cambios de comportamiento).
            reservado_local = sum(
                m.product_uom._compute_quantity(m.quantity, line.product_uom)
                for m in delivery_moves
            )

            if line.multi_stock_todo_origen:
                qty_origen = qty_total
            else:
                qty_origen = qty_total - reservado_local
            qty_origen = min(max(qty_origen, 0.0), qty_total)
            if float_is_zero(qty_origen, precision_rounding=rounding):
                # Todo disponible local -> R1 (entrega nativa).
                continue

            if not line.multi_stock_mode:
                # Bloqueante (pedido del analista): el mostrador debe decidir qué
                # hacer con el faltante; un aviso pasivo no se mira. Al levantarse
                # acá (post super), toda la confirmación hace rollback.
                raise UserError(
                    _(
                        "%(prod)s: faltan %(qty)s %(uom)s en este almacén. Elegí en la "
                        "línea cómo cumplir el faltante (Retira luego / Envío directo / "
                        "Se entrega lo existente) antes de confirmar."
                    )
                    % {
                        "prod": line.product_id.display_name,
                        "qty": qty_origen,
                        "uom": line.product_uom.name,
                    }
                )

            if line.multi_stock_mode == "retira_despues":
                picking_out, picking_in = self._multi_stock_gen_transfer(
                    line, qty_origen
                )
                self._multi_stock_split_delivery_defer(line, qty_origen, picking_in)
                qty_local = qty_total - qty_origen
                avisos.append(
                    _(
                        "%(prod)s: %(local)s %(uom)s se entregan ahora; %(qty)s %(uom)s "
                        "vía traslado (despacho %(out)s en el origen + recepción %(in)s "
                        "en el destino) y se entregan al recibir."
                    )
                    % {
                        "prod": line.product_id.display_name,
                        "local": qty_local,
                        "qty": qty_origen,
                        "uom": line.product_uom.name,
                        "out": picking_out.name,
                        "in": picking_in.name,
                    }
                )
            elif line.multi_stock_mode == "envio_directo":
                dropship = self._multi_stock_gen_dropship(line, qty_origen)
                self._multi_stock_reduce_delivery(line, qty_origen)
                avisos.append(
                    _(
                        "%(prod)s: %(qty)s %(uom)s por envío directo desde el origen "
                        "al cliente (%(ds)s). Se descontó esa cantidad de la entrega "
                        "del destino."
                    )
                    % {
                        "prod": line.product_id.display_name,
                        "qty": qty_origen,
                        "uom": line.product_uom.name,
                        "ds": dropship.name,
                    }
                )
            elif line.multi_stock_mode == "solo_existente":
                # No se interviene: se deja la entrega estándar (demanda completa,
                # con lo disponible ya reservado). Al validarla, Odoo muestra su
                # asistente nativo de backorder (entregar lo disponible y cancelar
                # el saldo, o crear una entrega del pendiente). No se auto-valida
                # porque la entrega no está totalmente reservada.
                continue

        if avisos:
            self._multi_stock_aviso(
                "\n".join(avisos),
                _("Multi depósito: documentos generados"),
            )

    # ------------------------------------------------------------------
    # Generadores de stock
    # ------------------------------------------------------------------
    def _multi_stock_gen_transfer(self, line, qty):
        """R2: crea despacho Origen->Tránsito (compañía del origen) y recepción
        Tránsito->Destino (compañía del destino). Devuelve (picking_out,
        picking_in). Ambos quedan para validación MANUAL. Ver SPEC 4.3."""
        self.ensure_one()
        wh = self.warehouse_id
        # sudo: el usuario de la sucursal puede estar SOLO en su compañía y no
        # tener acceso al almacén/compañía del origen. La generación del traslado
        # es una operación de sistema; se lee y crea con sudo para no exigirle al
        # vendedor acceso multicompañía. La recepción/despacho los valida después
        # quien corresponda en cada compañía.
        source_wh = wh.multi_stock_source_warehouse_id.sudo()
        transit = wh.multi_stock_transit_location_id
        product = line.product_id
        StockPicking = self.env["stock.picking"].sudo()

        picking_out = StockPicking.create(
            {
                "picking_type_id": wh.multi_stock_out_type_id.id,
                "company_id": source_wh.company_id.id,
                "location_id": source_wh.lot_stock_id.id,
                "location_dest_id": transit.id,
                "origin": self.name,
                "partner_id": self.partner_id.id,
                "multi_stock_sale_id": self.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "name": product.display_name,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": line.product_uom.id,
                            "location_id": source_wh.lot_stock_id.id,
                            "location_dest_id": transit.id,
                            "company_id": source_wh.company_id.id,
                            "procure_method": "make_to_stock",
                        },
                    )
                ],
            }
        )
        picking_in = StockPicking.create(
            {
                "picking_type_id": wh.multi_stock_in_type_id.id,
                "company_id": wh.company_id.id,
                "location_id": transit.id,
                "location_dest_id": wh.lot_stock_id.id,
                "origin": self.name,
                "partner_id": self.partner_id.id,
                "multi_stock_sale_id": self.id,
                # Vincula la recepción a su despacho: al validarse el despacho,
                # _multi_stock_spawn_reception ve que ya existe y no la duplica.
                "multi_stock_dispatch_id": picking_out.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "name": product.display_name,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": line.product_uom.id,
                            "location_id": transit.id,
                            "location_dest_id": wh.lot_stock_id.id,
                            "company_id": wh.company_id.id,
                            "procure_method": "make_to_stock",
                        },
                    )
                ],
            }
        )
        picking_out.action_confirm()
        picking_in.action_confirm()
        return picking_out, picking_in

    def _multi_stock_split_delivery_defer(self, line, qty_origen, picking_in):
        """Entrega ahora la porción disponible y DIFIERE ``qty_origen`` en un
        picking SEPARADO, encadenado (MTO) a la recepción del traslado. Así el
        cliente se lleva lo disponible y el saldo queda pendiente de entrega (y,
        con política de facturación por entrega, de facturación). Ver SPEC 4.3."""
        self.ensure_one()
        reception_move = picking_in.move_ids[:1]
        delivery_moves = self._multi_stock_delivery_moves(line)
        if not reception_move or not delivery_moves:
            return
        move = delivery_moves[0]
        product = line.product_id
        rounding = line.product_uom.rounding
        # move.product_uom_qty está en la UoM del move (referencia del producto)
        # y qty_origen en la UoM de la línea: se opera en la UoM de la línea y se
        # convierte de vuelta al escribir la demanda del move. Con UoM de línea
        # == UoM del producto las conversiones son identidad (caso normal).
        move_demand = move.product_uom._compute_quantity(
            move.product_uom_qty, line.product_uom
        )
        qty_local = max(move_demand - qty_origen, 0.0)

        move._do_unreserve()
        if float_is_zero(qty_local, precision_rounding=rounding):
            # Nada disponible local: toda la línea diferida -> move existente a MTO.
            move.write(
                {
                    "procure_method": "make_to_order",
                    "move_orig_ids": [(4, reception_move.id)],
                }
            )
            deferred_move = move
        else:
            # Entrego qty_local ahora (queda en su picking original, auto-validable)
            # y creo un picking SEPARADO para el saldo diferido.
            move.write(
                {
                    "product_uom_qty": line.product_uom._compute_quantity(
                        qty_local, move.product_uom
                    )
                }
            )
            move._action_assign()
            StockPicking = self.env["stock.picking"].sudo()
            deferred_picking = StockPicking.create(
                {
                    "picking_type_id": move.picking_type_id.id,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "partner_id": (self.partner_shipping_id or self.partner_id).id,
                    "company_id": move.company_id.id,
                    "origin": self.name,
                    "multi_stock_sale_id": self.id,
                }
            )
            deferred_move = (
                self.env["stock.move"]
                .sudo()
                .create(
                    {
                        "name": product.display_name,
                        "product_id": product.id,
                        "product_uom_qty": qty_origen,
                        "product_uom": line.product_uom.id,
                        "location_id": move.location_id.id,
                        "location_dest_id": move.location_dest_id.id,
                        "picking_id": deferred_picking.id,
                        "picking_type_id": move.picking_type_id.id,
                        "company_id": move.company_id.id,
                        "group_id": move.group_id.id,
                        "sale_line_id": line.id,
                        "origin": self.name,
                        "procure_method": "make_to_order",
                        "move_orig_ids": [(4, reception_move.id)],
                    }
                )
            )

        reception_move.write({"move_dest_ids": [(4, deferred_move.id)]})
        deferred_move._action_confirm(merge=False)

    def _multi_stock_gen_dropship(self, line, qty):
        """R3: crea el drop-ship Origen/Existencias -> Cliente (compañía del
        origen). Queda para validación/reparto MANUAL. Ver SPEC 4.4 y el riesgo
        contable (ingreso en la compañía del destino, costo en la del origen)."""
        self.ensure_one()
        wh = self.warehouse_id
        # sudo: ver _multi_stock_gen_transfer (el usuario puede no tener acceso a
        # la compañía/almacén del origen).
        source_wh = wh.multi_stock_source_warehouse_id.sudo()
        product = line.product_id
        partner = self.partner_shipping_id or self.partner_id
        customer_loc = partner.property_stock_customer or self.env.ref(
            "stock.stock_location_customers"
        )
        StockPicking = self.env["stock.picking"].sudo()
        picking = StockPicking.create(
            {
                "picking_type_id": wh.multi_stock_dropship_type_id.id,
                "company_id": source_wh.company_id.id,
                "location_id": source_wh.lot_stock_id.id,
                "location_dest_id": customer_loc.id,
                "partner_id": partner.id,
                "origin": self.name,
                "multi_stock_sale_id": self.id,
                "move_ids": [
                    (
                        0,
                        0,
                        {
                            "name": product.display_name,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": line.product_uom.id,
                            "location_id": source_wh.lot_stock_id.id,
                            "location_dest_id": customer_loc.id,
                            "company_id": source_wh.company_id.id,
                            "procure_method": "make_to_stock",
                            # Vincula la entrega real al pedido para que cuente como
                            # entregado (la entrega del destino se descontó).
                            "sale_line_id": line.id,
                        },
                    )
                ],
            }
        )
        picking.action_confirm()
        return picking

    def _multi_stock_reduce_delivery(self, line, qty):
        """Descuenta ``qty`` de la entrega del destino (R3): esa mercadería no
        pasa por el almacén destino. Si la línea es toda R3, cancela el move."""
        self.ensure_one()
        delivery_moves = self._multi_stock_delivery_moves(line)
        if not delivery_moves:
            return
        move = delivery_moves[0]
        rounding = line.product_uom.rounding
        # qty está en la UoM de la línea; la demanda del move en la UoM del move.
        # Se compara y opera en la UoM de la línea (identidad si coinciden).
        move_demand = move.product_uom._compute_quantity(
            move.product_uom_qty, line.product_uom
        )
        if float_compare(qty, move_demand, precision_rounding=rounding) >= 0:
            move._action_cancel()
        else:
            move._do_unreserve()
            move.write(
                {
                    "product_uom_qty": line.product_uom._compute_quantity(
                        move_demand - qty, move.product_uom
                    )
                }
            )
            move._action_assign()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _multi_stock_delivery_moves(self, line):
        """Moves de entrega al cliente (del almacén destino) de la línea,
        pendientes."""
        self.ensure_one()
        return line.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
            and m.location_dest_id.usage == "customer"
            and m.company_id == self.company_id
        )

    def _multi_stock_picking_auto_validable(self, picking):
        """True solo si el picking es una entrega LOCAL al cliente totalmente
        disponible (reservada desde stock real, sin forzar). Los pickings
        inter-almacén (otra compañía o desde tránsito) y el saldo diferido (en
        estado waiting) devuelven False.

        Lo usa el auto-validate de polpo (venta_directa / envio_automatico)."""
        self.ensure_one()
        if picking.state in ("done", "cancel"):
            return False
        if picking.company_id != self.company_id:
            # Despacho/drop-ship de la compañía del origen -> validación manual.
            return False
        transit = self.warehouse_id.multi_stock_transit_location_id
        moves = picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        if not moves:
            return False
        for move in moves:
            if move.location_dest_id.usage != "customer":
                return False
            if transit and move.location_id == transit:
                return False
            # Totalmente reservado desde disponibilidad real (sin setear a mano).
            if (
                float_compare(
                    move.quantity,
                    move.product_uom_qty,
                    precision_rounding=move.product_uom.rounding,
                )
                < 0
            ):
                return False
        return True

    def _multi_stock_aviso(self, mensaje, encabezado):
        """Aviso no bloqueante al responsable (mismo patrón que polpo)."""
        self.ensure_one()
        lineas = [escape(linea) for linea in mensaje.split("\n")]
        nota = Markup("<br/>").join(lineas)
        responsable = self.user_id.id or self.env.user.id
        self.activity_schedule(
            "mail.mail_activity_data_warning",
            summary=encabezado,
            note=nota,
            user_id=responsable,
        )
