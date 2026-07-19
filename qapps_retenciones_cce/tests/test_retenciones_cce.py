# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestRetencionesCce(AccountTestInvoicingCommon):
    """Tests del modulo qapps_retenciones_cce.

    Cubre: calculo de monto (NETO base imponible vs TOTAL con IVA), retencion por
    linea, CCE = amount_tax, asignacion de cuenta por tipo, computes/constraints/
    onchanges del modelo principal, el flujo de pago (devolucion) y el asiento de
    reclasificacion que reduce el residual de la factura.
    """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        # Impuesto 22% determinista (no dependemos de l10n_uy ni tasas del entorno)
        cls.iva_22 = cls.env["account.tax"].create({
            "name": "IVA 22% test",
            "amount_type": "percent",
            "amount": 22.0,
            "type_tax_use": "sale",
            "company_id": cls.company_data["company"].id,
        })

        # Cuentas para retencion en garantia y CCE en la compania
        cls.cuenta_retencion = cls.env["account.account"].create({
            "name": "Retenciones en garantia test",
            "code": "RETGAR1",
            "account_type": "liability_current",
            "company_id": cls.company_data["company"].id,
        })
        cls.cuenta_cce = cls.env["account.account"].create({
            "name": "CCE test",
            "code": "CCE0001",
            "account_type": "asset_current",
            "company_id": cls.company_data["company"].id,
        })
        cls.company_data["company"].write({
            "retention_warranty_account_id": cls.cuenta_retencion.id,
            "certificate_credit_account_id": cls.cuenta_cce.id,
        })

        cls.Retencion = cls.env["qapps.retenciones.cce"]
        cls.Payment = cls.env["account.payment"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _factura(cls, move_type="out_invoice", amounts=None, post=False):
        """Factura con IVA 22% determinista usando lineas por importe."""
        return cls.init_invoice(
            move_type,
            partner=cls.partner_a,
            amounts=amounts or [1000.0],
            taxes=cls.iva_22,
            post=post,
        )

    def _nueva_retencion(self, move, **vals):
        base = {"move_id": move.id}
        base.update(vals)
        return self.Retencion.create(base)

    def _buscar_reclass(self, move):
        """Localiza el asiento de reclasificacion generado al postear `move`.

        El modelo crea el asiento con ref = "Retenciones <move.name>", tomando
        `move.name` durante el pipeline de `_post`. En la base `qa_core`,
        `qapps_efactura` esta instalado y reasigna `move.name` (via su propia
        secuencia) DESPUES de que `qapps_retenciones_cce` ya capturo el nombre
        para el ref, por lo que un match exacto por `ref == "Retenciones " +
        move.name` no encuentra el asiento. Buscamos por prefijo de ref,
        acotado al partner y a move_type 'entry' (robusto e independiente del
        nombre final de la factura).
        """
        return self.env["account.move"].search([
            ("ref", "=like", "Retenciones %"),
            ("move_type", "=", "entry"),
            ("partner_id", "=", move.partner_id.id),
            ("company_id", "=", move.company_id.id),
        ])

    # ------------------------------------------------------------------
    # _compute_name
    # ------------------------------------------------------------------
    def test_compute_name_retention(self):
        move = self._factura()
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertEqual(ret.name, f"Retención en garantía - {move.name}")

    def test_compute_name_certificate(self):
        move = self._factura()
        ret = self._nueva_retencion(move, application_type="certificate")
        self.assertEqual(ret.name, f"Certificado de crédito fiscal - {move.name}")

    def test_compute_name_sin_move_usa_solo_label(self):
        # move_id es required, pero _compute_name tiene una rama para record sin move.
        # La forzamos via new() (registro en memoria) para cubrir la rama.
        ret = self.Retencion.new({"application_type": "retention"})
        self.assertEqual(ret.name, "Retención en garantía")

    # ------------------------------------------------------------------
    # _compute_amount  -  NETO (base imponible) vs TOTAL (con IVA)
    # ------------------------------------------------------------------
    def test_amount_retencion_base_toda_factura(self):
        # base imponible = 1000, pct 10% -> 100
        move = self._factura(amounts=[1000.0])
        self.assertEqual(move.amount_untaxed, 1000.0)
        self.assertEqual(move.amount_tax, 220.0)
        self.assertEqual(move.amount_total, 1220.0)
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertAlmostEqual(ret.amount, 100.0)

    def test_amount_retencion_total_toda_factura(self):
        # total con IVA = 1220, pct 10% -> 122
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="total", percentage=10.0
        )
        self.assertAlmostEqual(ret.amount, 122.0)

    def test_amount_retencion_base_vs_total_difieren_por_iva(self):
        move = self._factura(amounts=[1000.0])
        ret_base = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        ret_total = self._nueva_retencion(
            move, application_type="retention", base_calculation="total", percentage=10.0
        )
        # Diferencia = 10% del IVA (220) = 22
        self.assertAlmostEqual(ret_total.amount - ret_base.amount, 22.0)

    def test_amount_retencion_por_linea_base(self):
        # Dos lineas: 1000 y 500. Retencion sobre la de 1000 al 10%.
        move = self._factura(amounts=[1000.0, 500.0])
        linea_1000 = move.invoice_line_ids.filtered(
            lambda l: l.price_subtotal == 1000.0
        )
        ret = self._nueva_retencion(
            move,
            application_type="retention",
            base_calculation="base",
            percentage=10.0,
            invoice_line_ids=[Command.set(linea_1000.ids)],
        )
        # Solo la linea de 1000 (subtotal) -> 100, no la factura entera (1500)
        self.assertAlmostEqual(ret.amount, 100.0)

    def test_amount_retencion_por_linea_total(self):
        # Linea de 1000 -> price_total = 1220, pct 10% -> 122
        move = self._factura(amounts=[1000.0, 500.0])
        linea_1000 = move.invoice_line_ids.filtered(
            lambda l: l.price_subtotal == 1000.0
        )
        ret = self._nueva_retencion(
            move,
            application_type="retention",
            base_calculation="total",
            percentage=10.0,
            invoice_line_ids=[Command.set(linea_1000.ids)],
        )
        self.assertAlmostEqual(ret.amount, 122.0)

    def test_amount_retencion_varias_lineas(self):
        # Ambas lineas, base: (1000+500)*10% = 150
        move = self._factura(amounts=[1000.0, 500.0])
        lineas = move.invoice_line_ids.filtered(lambda l: l.display_type == "product")
        ret = self._nueva_retencion(
            move,
            application_type="retention",
            base_calculation="base",
            percentage=10.0,
            invoice_line_ids=[Command.set(lineas.ids)],
        )
        self.assertAlmostEqual(ret.amount, 150.0)

    def test_amount_certificate_es_amount_tax(self):
        # CCE = IVA total de la factura, ignora percentage/base
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="certificate", percentage=99.0
        )
        self.assertAlmostEqual(ret.amount, move.amount_tax)
        self.assertAlmostEqual(ret.amount, 220.0)

    def test_amount_recalcula_al_cambiar_percentage(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertAlmostEqual(ret.amount, 100.0)
        ret.percentage = 25.0
        self.assertAlmostEqual(ret.amount, 250.0)

    # ------------------------------------------------------------------
    # _compute_account_id  -  cuenta por tipo
    # ------------------------------------------------------------------
    def test_account_retention(self):
        move = self._factura()
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertEqual(ret.account_id, self.cuenta_retencion)

    def test_account_certificate(self):
        move = self._factura()
        ret = self._nueva_retencion(move, application_type="certificate")
        self.assertEqual(ret.account_id, self.cuenta_cce)

    def test_account_editable_y_recalcula_al_cambiar_tipo(self):
        # account_id es store=True readonly=False: recalcula al cambiar el tipo
        move = self._factura()
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertEqual(ret.account_id, self.cuenta_retencion)
        ret.application_type = "certificate"
        self.assertEqual(ret.account_id, self.cuenta_cce)

    # ------------------------------------------------------------------
    # _onchange_application_type
    # ------------------------------------------------------------------
    def test_onchange_application_type_limpia_campos(self):
        move = self._factura(amounts=[1000.0, 500.0])
        lineas = move.invoice_line_ids.filtered(lambda l: l.display_type == "product")
        ret = self.Retencion.new({
            "move_id": move.id,
            "application_type": "retention",
            "base_calculation": "total",
            "percentage": 10.0,
            "invoice_line_ids": [Command.set(lineas.ids)],
        })
        ret.application_type = "certificate"
        ret._onchange_application_type()
        self.assertFalse(ret.base_calculation)
        self.assertEqual(ret.percentage, 0.0)
        self.assertFalse(ret.invoice_line_ids)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    def test_constraint_retencion_requiere_base_calculation(self):
        move = self._factura()
        with self.assertRaises(ValidationError):
            self._nueva_retencion(
                move, application_type="retention", percentage=10.0
            )

    def test_constraint_certificate_no_requiere_base(self):
        # certificate sin base no debe fallar
        move = self._factura()
        ret = self._nueva_retencion(move, application_type="certificate")
        self.assertTrue(ret.id)

    def test_constraint_lineas_solo_en_retencion(self):
        move = self._factura(amounts=[1000.0])
        linea = move.invoice_line_ids.filtered(lambda l: l.display_type == "product")
        with self.assertRaises(ValidationError):
            self._nueva_retencion(
                move,
                application_type="certificate",
                invoice_line_ids=[Command.set(linea.ids)],
            )

    def test_constraint_lineas_deben_pertenecer_al_move(self):
        move_a = self._factura(amounts=[1000.0])
        move_b = self._factura(amounts=[500.0])
        linea_b = move_b.invoice_line_ids.filtered(lambda l: l.display_type == "product")
        with self.assertRaises(ValidationError):
            self._nueva_retencion(
                move_a,
                application_type="retention",
                base_calculation="base",
                percentage=10.0,
                invoice_line_ids=[Command.set(linea_b.ids)],
            )

    # ------------------------------------------------------------------
    # Asiento de reclasificacion  (_post)
    # ------------------------------------------------------------------
    def test_reclasificacion_out_invoice_reduce_residual(self):
        move = self._factura(amounts=[1000.0])  # total 1220
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )  # 100
        move.action_post()

        # Se genero un asiento de reclasificacion
        reclass = self._buscar_reclass(move)
        self.assertEqual(len(reclass), 1)
        self.assertEqual(reclass.state, "posted")

        # Debita la cuenta de retencion por 100
        linea_ret = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_retencion
        )
        self.assertAlmostEqual(linea_ret.debit, 100.0)
        self.assertAlmostEqual(linea_ret.credit, 0.0)

        # El residual de la factura se reduce en 100: 1220 - 100 = 1120
        self.assertAlmostEqual(move.amount_residual, 1120.0)

    def test_reclasificacion_reconcilia_receivable(self):
        move = self._factura(amounts=[1000.0])
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()

        reclass = self._buscar_reclass(move)
        receivable = move.line_ids.filtered(
            lambda l: l.account_type == "asset_receivable"
        )
        reclass_recv = reclass.line_ids.filtered(
            lambda l: l.account_id == receivable.account_id
        )
        # El apunte receivable del reclass tiene credito = 100 y esta conciliado
        self.assertAlmostEqual(reclass_recv.credit, 100.0)
        self.assertTrue(reclass_recv.reconciled or reclass_recv.matched_debit_ids
                        or reclass_recv.matched_credit_ids)

    def test_reclasificacion_certificate_usa_amount_tax(self):
        move = self._factura(amounts=[1000.0])  # IVA 220
        self._nueva_retencion(move, application_type="certificate")
        move.action_post()

        reclass = self._buscar_reclass(move)
        linea_cce = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_cce
        )
        self.assertAlmostEqual(linea_cce.debit, 220.0)
        # Residual: 1220 - 220 = 1000
        self.assertAlmostEqual(move.amount_residual, 1000.0)

    def test_reclasificacion_out_refund_invierte_signo(self):
        move = self._factura(move_type="out_refund", amounts=[1000.0])
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()

        reclass = self._buscar_reclass(move)
        # En refund, la cuenta de retencion va al credito (signo invertido)
        linea_ret = reclass.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_retencion
        )
        self.assertAlmostEqual(linea_ret.credit, 100.0)
        self.assertAlmostEqual(linea_ret.debit, 0.0)

    def test_reclasificacion_varias_retenciones(self):
        move = self._factura(amounts=[1000.0])  # base 1000, IVA 220, total 1220
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )  # 100
        self._nueva_retencion(move, application_type="certificate")  # 220
        move.action_post()

        reclass = self._buscar_reclass(move)
        # 2 retenciones -> 4 apuntes
        self.assertEqual(len(reclass.line_ids), 4)
        # Residual: 1220 - 100 - 220 = 900
        self.assertAlmostEqual(move.amount_residual, 900.0)

    def test_sin_reclasificacion_si_no_hay_retenciones(self):
        move = self._factura(amounts=[1000.0])
        move.action_post()
        reclass = self.env["account.move"].search([
            ("ref", "=", f"Retenciones {move.name}"),
        ])
        self.assertFalse(reclass)
        self.assertAlmostEqual(move.amount_residual, 1220.0)

    def test_reclasificacion_ignora_retencion_monto_cero(self):
        move = self._factura(amounts=[1000.0])
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=0.0
        )  # amount 0 -> ignorada
        move.action_post()
        reclass = self.env["account.move"].search([
            ("ref", "=", f"Retenciones {move.name}"),
        ])
        # Sin lineas validas -> no se crea asiento
        self.assertFalse(reclass)
        self.assertAlmostEqual(move.amount_residual, 1220.0)

    def test_in_invoice_no_genera_reclasificacion(self):
        # Solo out_invoice / out_refund generan asiento
        move = self.init_invoice(
            "in_invoice", partner=self.partner_a, amounts=[1000.0],
            taxes=self.iva_22,
        )
        self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()
        reclass = self.env["account.move"].search([
            ("ref", "=", f"Retenciones {move.name}"),
        ])
        self.assertFalse(reclass)

    # ------------------------------------------------------------------
    # account.payment  -  devolucion / regularizacion
    # ------------------------------------------------------------------
    def test_payment_onchange_retention_setea_amount(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()

        pago = self.Payment.new({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "application_type": "retention",
            "retention_id": ret.id,
        })
        pago._onchange_retention_id()
        self.assertAlmostEqual(pago.amount, 100.0)

    def test_payment_onchange_application_type_limpia_retention(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        pago = self.Payment.new({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "application_type": "retention",
            "retention_id": ret.id,
        })
        pago.application_type = "certificate"
        pago._onchange_application_type()
        self.assertFalse(pago.retention_id)

    def test_payment_destination_account_retention(self):
        pago = self.Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "amount": 100.0,
            "application_type": "retention",
        })
        self.assertEqual(pago.destination_account_id, self.cuenta_retencion)

    def test_payment_destination_account_certificate(self):
        pago = self.Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "amount": 220.0,
            "application_type": "certificate",
        })
        self.assertEqual(pago.destination_account_id, self.cuenta_cce)

    def test_payment_post_marca_retencion_cobrada(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()
        self.assertEqual(ret.state, "pending")

        fecha = fields.Date.from_string("2026-06-19")
        pago = self.Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "amount": ret.amount,
            "date": fecha,
            "application_type": "retention",
            "retention_id": ret.id,
        })
        pago.action_post()

        self.assertEqual(ret.state, "paid")
        self.assertEqual(ret.payment_id, pago)
        self.assertEqual(ret.payment_date, fecha)

    def test_payment_post_sin_retention_no_afecta(self):
        # Pago normal sin application_type/retention_id no toca nada
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        move.action_post()
        pago = self.Payment.create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner_a.id,
            "amount": 50.0,
        })
        pago.action_post()
        self.assertEqual(ret.state, "pending")
        self.assertFalse(ret.payment_id)

    # ------------------------------------------------------------------
    # Relaciones / related fields
    # ------------------------------------------------------------------
    def test_related_company_y_currency(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertEqual(ret.company_id, move.company_id)
        self.assertEqual(ret.currency_id, move.currency_id)

    def test_move_retention_cce_ids_one2many(self):
        move = self._factura(amounts=[1000.0])
        ret = self._nueva_retencion(
            move, application_type="retention", base_calculation="base", percentage=10.0
        )
        self.assertIn(ret, move.retention_cce_ids)
