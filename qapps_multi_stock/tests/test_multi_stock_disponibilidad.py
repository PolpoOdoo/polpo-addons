# Copyright 2026 QEI SRL (Polpo)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Tests del compute de disponibilidad por línea (sale.order.line).

Cubre _compute_multi_stock_disponibilidad:
- free_qty físico - reservado (NO qty_available),
- faltante = max(qty - free, 0),
- tiene_faltante solo si hay faltante Y el almacén está mapeado,
- conversión de UoM,
- servicios/consumibles ignorados (free=0, sin faltante).
"""
from odoo.tests import tagged

from .common import MultiStockCommon


@tagged("post_install", "-at_install")
class TestMultiStockDisponibilidad(MultiStockCommon):

    def test_sin_stock_local_da_faltante_total(self):
        prod = self._producto("Sin stock")
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 0.0)
        self.assertEqual(line.multi_stock_faltante, 10.0)
        self.assertTrue(line.multi_stock_tiene_faltante)

    def test_stock_local_suficiente_sin_faltante(self):
        prod = self._producto("Con stock")
        self._stock(prod, 20.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 20.0)
        self.assertEqual(line.multi_stock_faltante, 0.0)
        self.assertFalse(line.multi_stock_tiene_faltante)

    def test_stock_parcial_da_faltante_parcial(self):
        prod = self._producto("Parcial")
        self._stock(prod, 6.0, self.wh_dest)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 6.0)
        self.assertEqual(line.multi_stock_faltante, 4.0)
        self.assertTrue(line.multi_stock_tiene_faltante)

    def test_free_qty_descuenta_reservado(self):
        # free_qty = físico - reservado: una reserva previa baja la disponibilidad.
        prod = self._producto("Reservado")
        self._stock(prod, 10.0, self.wh_dest)
        # Reservo 7 con un move ajeno a la venta.
        move = self.env["stock.move"].sudo().create({
            "name": "reserva previa",
            "product_id": prod.id,
            "product_uom_qty": 7.0,
            "product_uom": prod.uom_id.id,
            "location_id": self.wh_dest.lot_stock_id.id,
            "location_dest_id": self.customer_loc.id,
            "company_id": self.company.id,
        })
        move._action_confirm()
        move._action_assign()
        self.assertEqual(move.quantity, 7.0)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        # Disponible libre = 10 - 7 = 3.
        self.assertEqual(line.multi_stock_free_local, 3.0)
        self.assertEqual(line.multi_stock_faltante, 7.0)

    def test_stock_en_origen_no_cuenta_como_local(self):
        # El stock está en el ORIGEN, no en el destino -> faltante total en destino.
        prod = self._producto("Stock en origen")
        self._stock(prod, 50.0, self.wh_src)
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 0.0)
        self.assertEqual(line.multi_stock_faltante, 10.0)
        self.assertTrue(line.multi_stock_tiene_faltante)

    def test_almacen_sin_mapeo_no_tiene_faltante(self):
        # Mismo faltante físico, pero el almacén ORIGEN no está mapeado para multi
        # depósito -> tiene_faltante = False (no se ofrece el selector).
        prod = self._producto("Sin mapeo")
        so = self._crear_venta(prod, 10.0, self.wh_src)  # wh_src no tiene source
        line = so.order_line
        self.assertEqual(line.multi_stock_faltante, 10.0)
        self.assertFalse(line.multi_stock_tiene_faltante)

    def test_servicio_ignorado(self):
        prod = self._producto("Servicio", tipo="service")
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 0.0)
        self.assertEqual(line.multi_stock_faltante, 0.0)
        self.assertFalse(line.multi_stock_tiene_faltante)

    def test_consumible_ignorado(self):
        prod = self._producto("Consumible", tipo="consu")
        so = self._crear_venta(prod, 10.0, self.wh_dest)
        line = so.order_line
        self.assertEqual(line.multi_stock_free_local, 0.0)
        self.assertEqual(line.multi_stock_faltante, 0.0)
        self.assertFalse(line.multi_stock_tiene_faltante)

    def test_conversion_de_uom(self):
        # Stock en unidades, venta en docenas: free se convierte a la UoM de la línea.
        prod = self._producto("UoM")
        self._stock(prod, 24.0, self.wh_dest)  # 24 unidades = 2 docenas
        docena = self.env.ref("uom.product_uom_dozen")
        so = self._crear_venta(prod, 3.0, self.wh_dest)
        so.order_line.product_uom = docena.id
        line = so.order_line
        # 24 unidades -> 2 docenas libres; faltante = 3 - 2 = 1 docena.
        self.assertEqual(line.multi_stock_free_local, 2.0)
        self.assertEqual(line.multi_stock_faltante, 1.0)
        self.assertTrue(line.multi_stock_tiene_faltante)
