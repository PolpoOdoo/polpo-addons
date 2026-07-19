# -*- coding: utf-8 -*-
"""Tests de qapps_codbarra (control de cantidades por lectura de código de barras).

IMPORTANTE — alcance real del módulo:
    A pesar de su nombre, este módulo NO genera ni valida códigos EAN13/GTIN13,
    PLU, DUN ni dígitos verificadores. No hay checksum ni `tipo_barcode` en el
    código. Lo que hace es:
      - stock.picking.read_barcode(barcode): busca el product.product cuyo
        `barcode` coincide y, si ese producto está en una línea del albarán,
        incrementa `qty_checked` en 1 (control de unidades por escaneo).
      - stock.picking.read_all_barcode(): marca todas las líneas como
        totalmente controladas (qty_checked = product_uom_qty).
      - stock.picking.write(): dispara read_barcode cuando se escribe `barcode`,
        y read_all_barcode + mensaje de chatter cuando se setea `checked_order`.
      - purchase.order.button_confirm(): pone en 0 la cantidad de los movimientos
        del picking recién generado.
      - wizard qapps.barcode.reader(.line): UI de escaneo que delega en el picking.

    Por eso estos tests cubren esa lógica (incremento, errores de control,
    auto-marcado de checked_order, read_all_barcode, override de write y del
    button_confirm de compra y la acción del wizard), NO checksums EAN.

Convenciones: TransactionCase, data propia por test, sin copiar res.company,
sin Form para campos fuera de vista, sin depender de data de ambiente.
"""
from odoo import fields
from odoo.tests import tagged, TransactionCase
from odoo.exceptions import UserError


@tagged("post_install", "-at_install")
class TestCodbarraBase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        cls.picking_type = cls.warehouse.out_type_id
        cls.loc_src = (cls.picking_type.default_location_src_id
                       or cls.env.ref('stock.stock_location_stock'))
        cls.loc_dest = (cls.picking_type.default_location_dest_id
                        or cls.env.ref('stock.stock_location_customers'))

        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Control SA'})

        cls.prod_a = cls.env['product.product'].create({
            'name': 'Producto A', 'type': 'consu', 'barcode': '7730000000017',
        })
        cls.prod_b = cls.env['product.product'].create({
            'name': 'Producto B', 'type': 'consu', 'barcode': '7730000000024',
        })
        # Producto que existe pero NO se cargará en el picking.
        cls.prod_ajeno = cls.env['product.product'].create({
            'name': 'Producto Ajeno', 'type': 'consu', 'barcode': '7730000000031',
        })

    def _picking(self):
        return self.env['stock.picking'].create({
            'picking_type_id': self.picking_type.id,
            'partner_id': self.partner.id,
            'location_id': self.loc_src.id,
            'location_dest_id': self.loc_dest.id,
        })

    def _move(self, picking, product, qty):
        return self.env['stock.move'].create({
            'name': product.name,
            'product_id': product.id,
            'product_uom_qty': qty,
            'product_uom': product.uom_id.id,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
        })

    def _line_for(self, picking, product):
        return picking.move_ids_without_package.filtered(
            lambda l: l.product_id == product)


# ---------------------------------------------------------------------------
# read_barcode: incremento de qty_checked
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestReadBarcode(TestCodbarraBase):

    def test_escaneo_valido_incrementa_qty_checked_en_uno(self):
        p = self._picking()
        self._move(p, self.prod_a, 3.0)
        p.read_barcode(self.prod_a.barcode)
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 1.0)

    def test_escaneos_sucesivos_acumulan(self):
        p = self._picking()
        self._move(p, self.prod_a, 3.0)
        p.read_barcode(self.prod_a.barcode)
        p.read_barcode(self.prod_a.barcode)
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 2.0)

    def test_escaneo_limpia_campo_barcode(self):
        # read_barcode setea self.barcode = None tras un match exitoso.
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        p.barcode = self.prod_a.barcode
        p.read_barcode(self.prod_a.barcode)
        self.assertFalse(p.barcode)

    def test_escaneo_solo_afecta_la_linea_correcta(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        self._move(p, self.prod_b, 2.0)
        p.read_barcode(self.prod_b.barcode)
        self.assertEqual(self._line_for(p, self.prod_b).qty_checked, 1.0)
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 0.0)

    def test_barcode_inexistente_lanza_usererror(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        with self.assertRaises(UserError):
            p.read_barcode('0000000000000')

    def test_producto_existente_pero_ajeno_a_la_orden_lanza_usererror(self):
        # El producto existe (tiene barcode) pero no está en ninguna línea.
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        with self.assertRaises(UserError):
            p.read_barcode(self.prod_ajeno.barcode)

    def test_exceso_sobre_reservado_lanza_usererror(self):
        # Si qty_checked ya alcanzó product_uom_qty, un escaneo más debe fallar.
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        p.read_barcode(self.prod_a.barcode)  # llega a 1.0 == reservado
        with self.assertRaises(UserError):
            p.read_barcode(self.prod_a.barcode)

    def test_qty_checked_no_supera_reservado_tras_error(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        p.read_barcode(self.prod_a.barcode)
        try:
            p.read_barcode(self.prod_a.barcode)
        except UserError:
            pass
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 1.0)


# ---------------------------------------------------------------------------
# checked_order: auto-marcado cuando todo está controlado
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestCheckedOrder(TestCodbarraBase):

    def test_no_se_marca_checked_order_con_pendientes(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        p.read_barcode(self.prod_a.barcode)  # 1 de 2
        self.assertFalse(p.checked_order)

    def test_se_marca_checked_order_cuando_unica_linea_completa(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        p.read_barcode(self.prod_a.barcode)
        p.read_barcode(self.prod_a.barcode)  # 2 de 2
        self.assertTrue(p.checked_order)

    def test_no_se_marca_checked_order_si_falta_otra_linea(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        self._move(p, self.prod_b, 1.0)
        p.read_barcode(self.prod_a.barcode)  # A completo, B pendiente
        self.assertFalse(p.checked_order)

    def test_se_marca_checked_order_con_todas_las_lineas_completas(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        self._move(p, self.prod_b, 1.0)
        p.read_barcode(self.prod_a.barcode)
        p.read_barcode(self.prod_b.barcode)
        self.assertTrue(p.checked_order)


# ---------------------------------------------------------------------------
# read_all_barcode: marca todo como controlado
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestReadAllBarcode(TestCodbarraBase):

    def test_read_all_iguala_qty_checked_a_reservado(self):
        p = self._picking()
        self._move(p, self.prod_a, 4.0)
        self._move(p, self.prod_b, 7.0)
        p.read_all_barcode()
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 4.0)
        self.assertEqual(self._line_for(p, self.prod_b).qty_checked, 7.0)

    def test_read_all_sobrescribe_parcial(self):
        p = self._picking()
        self._move(p, self.prod_a, 5.0)
        p.read_barcode(self.prod_a.barcode)  # 1 de 5
        p.read_all_barcode()
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 5.0)


# ---------------------------------------------------------------------------
# write(): dispara read_barcode y read_all_barcode + chatter
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestWriteOverride(TestCodbarraBase):

    def test_write_barcode_dispara_control(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        p.write({'barcode': self.prod_a.barcode})
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 1.0)

    def test_write_barcode_invalido_lanza_usererror(self):
        p = self._picking()
        self._move(p, self.prod_a, 2.0)
        with self.assertRaises(UserError):
            p.write({'barcode': '0000000000000'})

    def test_write_checked_order_true_completa_todas_las_lineas(self):
        # Setear checked_order=True llama read_all_barcode + crea mail.message.
        p = self._picking()
        self._move(p, self.prod_a, 3.0)
        self._move(p, self.prod_b, 2.0)
        p.write({'checked_order': True})
        self.assertEqual(self._line_for(p, self.prod_a).qty_checked, 3.0)
        self.assertEqual(self._line_for(p, self.prod_b).qty_checked, 2.0)

    def test_write_checked_order_setea_usuario_y_fecha_control(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        p.write({'checked_order': True})
        self.assertTrue(p.controller_user)
        self.assertTrue(p.controller_date)

    def test_write_checked_order_crea_mensaje_chatter(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        msgs_before = self.env['mail.message'].search_count([
            ('model', '=', 'stock.picking'), ('res_id', '=', p.id)])
        p.write({'checked_order': True})
        msgs_after = self.env['mail.message'].search_count([
            ('model', '=', 'stock.picking'), ('res_id', '=', p.id)])
        self.assertGreater(msgs_after, msgs_before)

    def test_write_date_done_con_control_marca_checked_order(self):
        # Si se completa date_done y hay alguna línea controlada, checked_order=True.
        p = self._picking()
        self._move(p, self.prod_a, 3.0)
        p.read_barcode(self.prod_a.barcode)  # 1 línea controlada parcial
        self.assertFalse(p.checked_order)
        p.write({'date_done': fields.Datetime.now()})
        self.assertTrue(p.checked_order)

    def test_write_date_done_sin_control_no_marca_checked_order(self):
        p = self._picking()
        self._move(p, self.prod_a, 3.0)  # nada controlado
        p.write({'date_done': fields.Datetime.now()})
        self.assertFalse(p.checked_order)


# ---------------------------------------------------------------------------
# purchase.order.button_confirm: pone en 0 la cantidad de los movimientos
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestPurchaseButtonConfirm(TestCodbarraBase):

    def test_confirmar_compra_pone_quantity_en_cero(self):
        vendor = self.env['res.partner'].create({'name': 'Proveedor Control SA'})
        prod = self.env['product.product'].create({
            'name': 'Insumo Compra', 'type': 'consu',
            'purchase_ok': True, 'barcode': '7730000000048',
        })
        order = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'order_line': [(0, 0, {
                'product_id': prod.id,
                'product_qty': 10.0,
                'product_uom': prod.uom_id.id,
                'price_unit': 5.0,
                'name': prod.name,
                'date_planned': fields.Datetime.now(),
            })],
        })
        order.button_confirm()
        self.assertTrue(order.picking_ids)
        for move in order.picking_ids.move_ids:
            self.assertEqual(move.quantity, 0.0)


# ---------------------------------------------------------------------------
# wizard_barcode_reader_action: acción de ventana con contexto
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestWizardAction(TestCodbarraBase):

    def test_action_devuelve_dict_correcto_con_picking_en_contexto(self):
        p = self._picking()
        self._move(p, self.prod_a, 1.0)
        action = p.wizard_barcode_reader_action()
        self.assertEqual(action['res_model'], 'qapps.barcode.reader')
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['target'], 'new')
        self.assertEqual(action['context'].get('stock_picking_active_id'), p.id)


# ---------------------------------------------------------------------------
# stock.move: campo qty_checked
# ---------------------------------------------------------------------------
@tagged("post_install", "-at_install")
class TestStockMoveField(TestCodbarraBase):

    def test_qty_checked_default_cero(self):
        p = self._picking()
        move = self._move(p, self.prod_a, 2.0)
        self.assertEqual(move.qty_checked, 0.0)
