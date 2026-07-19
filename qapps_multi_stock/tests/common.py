# Copyright 2026 QEI SRL (Polpo)
# License OPL-1 (Odoo Proprietary License v1.0).
"""Base común para los tests de qapps_multi_stock.

Arma dos almacenes en la MISMA compañía (DESTINO = almacén de la venta,
ORIGEN = almacén de reabastecimiento), una ubicación de tránsito compartida
(company_id vacío, como exige el modelo) y los tipos de operación para
despacho/recepción/drop-ship. Se mantiene mono-compañía a propósito: la regla
del proyecto pide NO copiar res.company y el motor de ruteo
(_multi_stock_apply y compañeros) se ejercita igual con dos almacenes locales,
ya que el código lee company_id desde el source_warehouse de forma genérica.

Para el aislamiento entre tests cada caso crea su producto y ajusta su propio
stock; nada depende de data de ambiente.
"""

from odoo.tests import Form

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class MultiStockCommon(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a

        Warehouse = cls.env["stock.warehouse"].sudo()
        Location = cls.env["stock.location"].sudo()
        PickingType = cls.env["stock.picking.type"].sudo()

        # Almacén DESTINO (donde se hace la venta sin tener stock) y su origen.
        cls.wh_dest = Warehouse.create({
            "name": "Sucursal Comercial (destino)",
            "code": "MSDST",
            "company_id": cls.company.id,
        })
        cls.wh_src = Warehouse.create({
            "name": "Depósito Central (origen)",
            "code": "MSSRC",
            "company_id": cls.company.id,
        })

        # Tránsito compartido: company_id vacío (lo exige el dominio del modelo).
        cls.transit = Location.create({
            "name": "Tránsito Multi Depósito",
            "usage": "transit",
            "company_id": False,
        })

        # Tipos de operación para despacho / recepción / drop-ship.
        cls.type_out = PickingType.create({
            "name": "MS Despacho",
            "code": "internal",
            "sequence_code": "MSOUT",
            "company_id": cls.company.id,
            "warehouse_id": cls.wh_src.id,
            "default_location_src_id": cls.wh_src.lot_stock_id.id,
            "default_location_dest_id": cls.transit.id,
        })
        cls.type_in = PickingType.create({
            "name": "MS Recepción",
            "code": "internal",
            "sequence_code": "MSIN",
            "company_id": cls.company.id,
            "warehouse_id": cls.wh_dest.id,
            "default_location_src_id": cls.transit.id,
            "default_location_dest_id": cls.wh_dest.lot_stock_id.id,
        })
        cls.customer_loc = cls.env.ref("stock.stock_location_customers")
        cls.type_dropship = PickingType.create({
            "name": "MS Envío Directo",
            "code": "outgoing",
            "sequence_code": "MSDS",
            "company_id": cls.company.id,
            "warehouse_id": cls.wh_src.id,
            "default_location_src_id": cls.wh_src.lot_stock_id.id,
            "default_location_dest_id": cls.customer_loc.id,
        })

        # Mapeo multi depósito en el almacén DESTINO.
        cls.wh_dest.write({
            "multi_stock_source_warehouse_id": cls.wh_src.id,
            "multi_stock_transit_location_id": cls.transit.id,
            "multi_stock_out_type_id": cls.type_out.id,
            "multi_stock_in_type_id": cls.type_in.id,
            "multi_stock_dropship_type_id": cls.type_dropship.id,
        })

    # ------------------------------------------------------------------ #
    #  Helpers de data por test                                          #
    # ------------------------------------------------------------------ #
    @classmethod
    def _producto(cls, nombre="MS Prod", tipo="product"):
        return cls.env["product.product"].create({
            "name": nombre,
            "type": tipo,
            "invoice_policy": "delivery",
            "uom_id": cls.env.ref("uom.product_uom_unit").id,
            "uom_po_id": cls.env.ref("uom.product_uom_unit").id,
        })

    @classmethod
    def _stock(cls, product, qty, warehouse):
        """Coloca stock físico del producto en el depósito del almacén dado."""
        cls.env["stock.quant"].sudo()._update_available_quantity(
            product, warehouse.lot_stock_id, qty
        )

    def _crear_venta(self, product, qty, warehouse, modo=None, todo_origen=False):
        """Crea (sin confirmar) una venta en el almacén dado con una línea."""
        so = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "warehouse_id": warehouse.id,
            "company_id": self.company.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": qty,
                "price_unit": 100.0,
            })],
        })
        vals = {}
        if modo is not None:
            vals["multi_stock_mode"] = modo
        if todo_origen:
            vals["multi_stock_todo_origen"] = True
        if vals:
            so.order_line.write(vals)
        return so

    def _delivery_moves(self, line):
        return line.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
            and m.location_dest_id.usage == "customer"
        )
