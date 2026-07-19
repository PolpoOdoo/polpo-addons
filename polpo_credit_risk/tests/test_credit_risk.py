# Copyright 2026 QAPPS
# License OPL-1 (Odoo Proprietary License v1.0).
"""Tests de caracterización para polpo_credit_risk.

Módulo bajo prueba: bloqueo por riesgo crediticio extendido. Extiende
sale_financial_risk / account_financial_risk (OCA). Cubre:

models/res_partner.py
  - _compute_effective_credit_limit / additional_credit_is_active
    (crédito adicional temporal: monto + ambas fechas + hoy en rango).
  - _onchange_additional_credit_coherence (warning no bloqueante).
  - _compute_risk_exception (override: usa effective_credit_limit en vez de
    credit_limit; suma de rubros incluidos -> risk_total).
  - _get_credit_exception_messages (acumula TODOS los motivos de bloqueo:
    deuda vencida, límite de pedidos, límite de facturas abiertas, límite de
    cheques diferidos, riesgo total vs límite efectivo).
  - _risk_field_list (agrega rubro cheques diferidos).

models/sale_order.py
  - _get_risk_extra_amount, evaluate_risk_message, _compute_credit_warning_msg.
  - action_confirm (bypass si credit_override_flag; abre wizard si hay bloqueo).

models/account_move.py
  - risk_exception_msg, _first_invoice_exception_msg, action_post
    (abre wizard; respeta allow_overrisk_invoice_validation y credit_override_flag).

wizards/credit_override_wizard.py
  - _compute_can_authorize, button_authorize (permiso, write de override,
    chatter, continúa la operación con bypass_risk).

RUBROS NEGATIVOS (corregido 2026-07-10): _compute_risk_exception normaliza a 0
los rubros incluidos negativos al sumar risk_total. Un rubro incluido negativo
(p.ej. un cliente con saldo a favor) ya NO rebaja risk_total ni puede enmascarar
un exceso real. El comportamiento correcto se prueba en test_rubro_negativo_*.

Convenciones: data propia por test, rollback por TransactionCase. Donde el
compute depende del entorno (tasas/monedas/cuentas), se setean los campos de
riesgo del partner de forma directa para aislar la lógica de bloqueo del módulo,
que es lo que se quiere probar. Donde es determinístico, se usan ventas reales.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestCreditRisk(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company_currency = cls.company.currency_id
        # Moneda de riesgo del partner_a = moneda de la compañía (credit_currency
        # por defecto = "company"), así evitamos depender de tasas del entorno.
        cls.cliente = cls.partner_a
        cls.cliente.credit_currency = "company"
        cls.hoy = fields.Date.context_today(cls.cliente)

        # Usuario SIN permiso de autorización (vendedor): sale_financial_risk
        # implica account_financial_risk.group_account_financial_risk_user.
        cls.user_vendedor = cls.env["res.users"].create({
            "name": "Vendedor sin override",
            "login": "vendedor_credit_test",
            "email": "vendedor@example.com",
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("sales_team.group_sale_salesman").id,
            ])],
        })
        # Usuario CON permiso de autorización. Ademas del grupo de autorizador,
        # un autorizador de credito real puede actuar sobre el documento bloqueado
        # para liberarlo (escribir el override y continuar la operacion). Por eso
        # se le otorgan los grupos funcionales necesarios:
        #   - sales_team.group_sale_manager: escribir cualquier sale.order (no solo
        #     las propias; el autorizador no es el vendedor del pedido).
        #   - account.group_account_user: leer/postear account.move (posteo de
        #     factura tras autorizar).
        # Sin estos grupos, button_authorize falla con AccessError al hacer
        # origin.write()/action_post() sobre documentos de otro usuario.
        cls.user_autorizador = cls.env["res.users"].create({
            "name": "Autorizador de crédito",
            "login": "autorizador_credit_test",
            "email": "autorizador@example.com",
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("sales_team.group_sale_salesman").id,
                cls.env.ref("sales_team.group_sale_manager").id,
                cls.env.ref("account.group_account_user").id,
                cls.env.ref(
                    "polpo_credit_risk.group_credit_authorizer"
                ).id,
            ])],
        })

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _venta(self, amount=None, partner=None, confirm=False, products=None):
        """Crea (y opcionalmente confirma) una sale.order simple.

        Cuando confirm=True la orden se usa para SEMBRAR riesgo (alimentar
        risk_sale_order del cliente). La confirmación se hace con
        bypass_risk=True para que NO sea interceptada por el propio bloqueo de
        crédito del módulo: muchos tests fijan un credit_limit bajo antes de
        sembrar, y sin el bypass action_confirm devolvería el wizard y dejaría la
        orden en draft (no aportaría a risk_sale_order).
        """
        partner = partner or self.cliente
        order = self.env["sale.order"].create({
            "partner_id": partner.id,
            "order_line": [(0, 0, {
                "product_id": (products or self.product_a).id,
                "product_uom_qty": 1,
                "price_unit": amount if amount is not None else 100.0,
            })],
        })
        if confirm:
            order.with_context(bypass_risk=True).action_confirm()
        return order

    # ================================================================== #
    #  1. CRÉDITO ADICIONAL TEMPORAL  (effective_credit_limit)           #
    # ================================================================== #
    def test_limite_efectivo_sin_adicional_es_credit_limit(self):
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 0.0
        self.assertEqual(self.cliente.effective_credit_limit, 1000.0)
        self.assertFalse(self.cliente.additional_credit_is_active)

    def test_limite_efectivo_adicional_vigente_se_suma(self):
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = self.hoy - timedelta(days=1)
        self.cliente.additional_credit_date_to = self.hoy + timedelta(days=1)
        self.assertTrue(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1500.0)

    def test_limite_efectivo_adicional_vencido_no_aplica(self):
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = self.hoy - timedelta(days=10)
        self.cliente.additional_credit_date_to = self.hoy - timedelta(days=1)
        self.assertFalse(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1000.0)

    def test_limite_efectivo_adicional_futuro_no_aplica(self):
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = self.hoy + timedelta(days=1)
        self.cliente.additional_credit_date_to = self.hoy + timedelta(days=10)
        self.assertFalse(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1000.0)

    def test_limite_efectivo_borde_hoy_es_desde_inclusive(self):
        # Rango [hoy, hoy] -> vigente (comparación inclusiva en ambos extremos).
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 200.0
        self.cliente.additional_credit_date_from = self.hoy
        self.cliente.additional_credit_date_to = self.hoy
        self.assertTrue(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1200.0)

    def test_limite_efectivo_monto_sin_fechas_no_aplica(self):
        # Monto cargado pero faltan fechas -> NO vigente (el compute lo ignora).
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = False
        self.cliente.additional_credit_date_to = False
        self.assertFalse(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1000.0)

    def test_limite_efectivo_solo_fecha_desde_no_aplica(self):
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = self.hoy
        self.cliente.additional_credit_date_to = False
        self.assertFalse(self.cliente.additional_credit_is_active)
        self.assertEqual(self.cliente.effective_credit_limit, 1000.0)

    # --- onchange de coherencia (warning no bloqueante) --------------- #
    def test_onchange_coherencia_monto_sin_fechas_avisa(self):
        partner = self.env["res.partner"].new({
            "name": "Coherencia 1",
            "additional_credit_amount": 100.0,
        })
        res = partner._onchange_additional_credit_coherence()
        self.assertTrue(res and "warning" in res)

    def test_onchange_coherencia_fechas_sin_monto_avisa(self):
        partner = self.env["res.partner"].new({
            "name": "Coherencia 2",
            "additional_credit_date_from": self.hoy,
            "additional_credit_date_to": self.hoy + timedelta(days=5),
        })
        res = partner._onchange_additional_credit_coherence()
        self.assertTrue(res and "warning" in res)

    def test_onchange_coherencia_desde_mayor_hasta_avisa(self):
        partner = self.env["res.partner"].new({
            "name": "Coherencia 3",
            "additional_credit_amount": 100.0,
            "additional_credit_date_from": self.hoy + timedelta(days=5),
            "additional_credit_date_to": self.hoy,
        })
        res = partner._onchange_additional_credit_coherence()
        self.assertTrue(res and "warning" in res)

    def test_onchange_coherencia_ok_no_avisa(self):
        partner = self.env["res.partner"].new({
            "name": "Coherencia 4",
            "additional_credit_amount": 100.0,
            "additional_credit_date_from": self.hoy,
            "additional_credit_date_to": self.hoy + timedelta(days=5),
        })
        res = partner._onchange_additional_credit_coherence()
        self.assertFalse(res)

    # ================================================================== #
    #  2. _compute_risk_exception (override usa effective_credit_limit)  #
    # ================================================================== #
    def test_risk_exception_usa_limite_efectivo(self):
        # risk_total construido vía rubro incluido. Usamos risk_sale_order_include
        # alimentando risk_sale_order con una venta real para tener un valor
        # determinístico independiente de tasas.
        self.cliente.credit_limit = 50.0
        self.cliente.risk_sale_order_include = True
        self._venta(amount=100.0, confirm=True)
        self.cliente.invalidate_recordset(["risk_sale_order", "risk_total"])
        # risk_total ~ 100 (price_total con impuestos), > credit_limit 50.
        self.assertGreater(self.cliente.risk_total, 50.0)
        self.assertTrue(self.cliente.risk_exception)

        # Ahora el crédito adicional vigente sube el límite efectivo por encima
        # del riesgo -> ya no hay excepción.
        self.cliente.additional_credit_amount = 10000.0
        self.cliente.additional_credit_date_from = self.hoy
        self.cliente.additional_credit_date_to = self.hoy + timedelta(days=1)
        self.cliente.invalidate_recordset(["risk_total", "risk_exception"])
        self.assertGreater(self.cliente.effective_credit_limit, 10000.0)
        self.assertFalse(self.cliente.risk_exception)

    def test_credito_disponible_usa_limite_efectivo(self):
        # Override de _compute_risk_remaining: el disponible se calcula contra
        # el límite efectivo (base + adicional vigente), no solo credit_limit.
        self.cliente.credit_limit = 1000.0
        self.cliente.additional_credit_amount = 0.0
        self.cliente.invalidate_recordset(
            ["risk_remaining_value", "risk_remaining_percentage"]
        )
        # Sin adicional: disponible = límite base - riesgo total (0).
        self.assertEqual(self.cliente.risk_remaining_value, 1000.0)
        self.assertEqual(self.cliente.risk_remaining_percentage, 100)

        self.cliente.additional_credit_amount = 500.0
        self.cliente.additional_credit_date_from = self.hoy
        self.cliente.additional_credit_date_to = self.hoy
        self.cliente.invalidate_recordset(
            ["risk_remaining_value", "risk_remaining_percentage"]
        )
        self.assertEqual(self.cliente.risk_remaining_value, 1500.0)

    def test_risk_exception_rubro_propio_cheques_limite(self):
        # El override añade el rubro (risk_deferred_checks, _limit, _include).
        # Sin tocar cheques reales: forzamos un límite específico excedido vía
        # rubro de pedidos para validar amount_exceeded del override.
        self.cliente.credit_limit = 0.0  # sin límite global
        self.cliente.risk_sale_order_limit = 30.0
        self._venta(amount=100.0, confirm=True)
        self.cliente.invalidate_recordset(
            ["risk_sale_order", "risk_total", "risk_exception"]
        )
        # max_value (30) y field_value (~100) > max -> excepción por límite rubro.
        self.assertTrue(self.cliente.risk_exception)
        self.assertGreater(self.cliente.risk_amount_exceeded, 0.0)

    def test_risk_field_list_incluye_cheques_diferidos(self):
        lst = self.env["res.partner"]._risk_field_list()
        tripletas = [t[0] for t in lst]
        self.assertIn("risk_deferred_checks", tripletas)
        self.assertIn("risk_sale_order", tripletas)  # de sale_financial_risk

    # ================================================================== #
    #  3. _get_credit_exception_messages  (acumula TODOS los motivos)    #
    # ================================================================== #
    def test_mensajes_sin_riesgo_lista_vacia(self):
        self.cliente.credit_limit = 1000000.0
        msgs = self.cliente._get_credit_exception_messages(extra_amount=0.0)
        self.assertEqual(msgs, [])

    def _stub_deuda_vencida(self, unpaid_amount):
        """Fija risk_invoice_unpaid de forma estable sobreescribiendo su
        compute (revertido por patch al terminar).

        El método bajo prueba invalida y recomputa risk_invoice_unpaid
        (computed OCA), por lo que no se puede inyectar en cache. El stub debe
        asignar TODOS los campos de _compute_risk_account_amount: si el compute
        no asigna alguno el ORM lanza "Compute method failed to assign ...".
        """
        Partner = type(self.cliente)

        def stub_compute(records):
            for rec in records:
                rec.risk_invoice_draft = 0.0
                rec.risk_invoice_open = 0.0
                rec.risk_invoice_unpaid = unpaid_amount
                rec.risk_account_amount = 0.0
                rec.risk_account_amount_unpaid = 0.0

        # patch() de BaseCase revierte automáticamente al terminar el test.
        self.patch(Partner, "_compute_risk_account_amount", stub_compute)

    def test_mensajes_deuda_vencida_con_include_activado(self):
        # Rama 1 de _get_credit_exception_messages: risk_invoice_unpaid > 0
        # bloquea SOLO si el cliente tiene risk_invoice_unpaid_include activado.
        self._stub_deuda_vencida(250.0)
        self.cliente.credit_limit = 1000000.0
        self.cliente.risk_invoice_unpaid_include = True
        msgs = self.cliente._get_credit_exception_messages()
        self.assertTrue(any("deuda vencida" in m for m in msgs))

    def test_mensajes_deuda_vencida_sin_include_no_bloquea(self):
        # Cliente NO parametrizado (include desactivado): aunque tenga deuda
        # vencida real, no se genera motivo de bloqueo. Este era el bug que
        # bloqueaba todas las ventas en producción: el chequeo ignoraba la
        # parametrización del cliente.
        self._stub_deuda_vencida(250.0)
        self.cliente.credit_limit = 0.0
        self.cliente.risk_invoice_unpaid_include = False
        msgs = self.cliente._get_credit_exception_messages()
        self.assertEqual(msgs, [])

    def test_cliente_sin_parametrizar_confirma_venta_con_deuda_vencida(self):
        # Integración: cliente con deuda vencida pero sin ningún control
        # activado (todos los include en False, límites en 0) confirma la
        # venta directo, sin wizard.
        self._stub_deuda_vencida(500.0)
        self.cliente.credit_limit = 0.0
        self.cliente.risk_invoice_unpaid_include = False
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        self.assertTrue(res)
        self.assertEqual(order.state, "sale")

    def test_mensajes_limite_pedidos_solo_en_contexto_sale(self):
        self.cliente.credit_limit = 0.0
        self.cliente.risk_sale_order_limit = 10.0
        self._venta(amount=100.0, confirm=True)
        self.cliente.invalidate_recordset(["risk_sale_order"])
        # En contexto 'sale': la rama de límite de pedidos dispara mensaje.
        msgs_sale = self.cliente._get_credit_exception_messages(
            extra_amount=0.0, context_doc="sale"
        )
        self.assertTrue(any("límite de riesgo de pedidos" in m for m in msgs_sale))
        # En contexto 'invoice' esa rama NO se evalúa.
        msgs_inv = self.cliente._get_credit_exception_messages(
            extra_amount=0.0, context_doc="invoice"
        )
        self.assertFalse(
            any("límite de riesgo de pedidos" in m for m in msgs_inv)
        )

    def test_mensajes_limite_facturas_abiertas_solo_contexto_invoice(self):
        # Sin facturas reales, risk_invoice_open=0; forzamos el límite muy bajo
        # y extra_amount alto para disparar la rama (0 + extra > limit).
        self.cliente.credit_limit = 0.0
        self.cliente.risk_invoice_open_limit = 10.0
        msgs_inv = self.cliente._get_credit_exception_messages(
            extra_amount=500.0, context_doc="invoice"
        )
        self.assertTrue(
            any("facturas abiertas" in m for m in msgs_inv)
        )
        # En contexto 'sale' no se evalúa esa rama.
        msgs_sale = self.cliente._get_credit_exception_messages(
            extra_amount=500.0, context_doc="sale"
        )
        self.assertFalse(any("facturas abiertas" in m for m in msgs_sale))

    def test_mensajes_riesgo_total_vs_limite_efectivo(self):
        # extra_amount empuja por encima del límite efectivo.
        self.cliente.credit_limit = 100.0
        self.cliente.additional_credit_amount = 0.0
        msgs = self.cliente._get_credit_exception_messages(
            extra_amount=500.0, context_doc="sale"
        )
        self.assertTrue(any("riesgo financiero total" in m for m in msgs))

    def test_mensajes_acumula_varios_motivos(self):
        # Límite de pedidos + límite total efectivo simultáneos.
        self.cliente.credit_limit = 50.0
        self.cliente.risk_sale_order_limit = 10.0
        self._venta(amount=100.0, confirm=True)
        self.cliente.invalidate_recordset(["risk_sale_order", "risk_total"])
        msgs = self.cliente._get_credit_exception_messages(
            extra_amount=200.0, context_doc="sale"
        )
        # Al menos dos motivos distintos.
        self.assertGreaterEqual(len(msgs), 2)

    # ================================================================== #
    #  4. SALE ORDER: warning, extra_amount, action_confirm + wizard     #
    # ================================================================== #
    def test_get_risk_extra_amount_misma_moneda(self):
        order = self._venta(amount=123.0)
        extra = order._get_risk_extra_amount(self.cliente)
        # moneda de riesgo = moneda compañía = moneda de la orden -> sin conversión.
        self.assertAlmostEqual(extra, order.amount_total, places=2)

    def test_get_risk_extra_amount_cero_si_total_cero(self):
        order = self._venta(amount=0.0)
        self.assertEqual(order._get_risk_extra_amount(self.cliente), 0.0)

    def test_warning_msg_en_borrador_cuando_excede(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)  # draft
        order.invalidate_recordset(["credit_warning_msg"])
        self.assertTrue(order.credit_warning_msg)
        self.assertIn("Advertencia de crédito", order.credit_warning_msg)

    def test_warning_msg_vacio_si_no_excede(self):
        self.cliente.credit_limit = 1000000.0
        order = self._venta(amount=100.0)
        order.invalidate_recordset(["credit_warning_msg"])
        self.assertFalse(order.credit_warning_msg)

    def test_warning_msg_vacio_si_flag_override(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        order.credit_override_flag = True
        order.invalidate_recordset(["credit_warning_msg"])
        self.assertFalse(order.credit_warning_msg)

    def test_action_confirm_sin_riesgo_confirma_directo(self):
        self.cliente.credit_limit = 1000000.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        self.assertTrue(res)
        self.assertEqual(order.state, "sale")

    def test_action_confirm_con_riesgo_abre_wizard(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        # Devuelve la acción del wizard, la orden NO se confirma.
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "polpo.credit.override.wiz")
        self.assertEqual(order.state, "draft")

    def test_action_confirm_con_flag_bypassa_riesgo(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        order.credit_override_flag = True
        order.action_confirm()
        # Con flag, salta la evaluación y confirma (no abre wizard).
        self.assertEqual(order.state, "sale")

    def test_action_confirm_wizard_referencia_y_metodo(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        wiz = self.env["polpo.credit.override.wiz"].browse(res["res_id"])
        self.assertEqual(wiz.partner_id, self.cliente.commercial_partner_id)
        self.assertEqual(wiz.continue_method, "action_confirm")
        self.assertEqual(wiz.origin_reference, order)
        self.assertTrue(wiz.exception_msg)

    # ================================================================== #
    #  5. ACCOUNT MOVE: risk_exception_msg, action_post, wizard          #
    # ================================================================== #
    def test_factura_sin_riesgo_postea_directo(self):
        self.cliente.credit_limit = 1000000.0
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        inv.action_post()
        self.assertEqual(inv.state, "posted")

    def test_factura_con_riesgo_abre_wizard(self):
        self.cliente.credit_limit = 1.0
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        res = inv.action_post()
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "polpo.credit.override.wiz")
        self.assertEqual(inv.state, "draft")
        wiz = self.env["polpo.credit.override.wiz"].browse(res["res_id"])
        self.assertEqual(wiz.continue_method, "action_post")
        self.assertEqual(wiz.origin_reference, inv)

    def test_factura_con_flag_override_no_bloquea(self):
        self.cliente.credit_limit = 1.0
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        inv.credit_override_flag = True
        inv.action_post()
        self.assertEqual(inv.state, "posted")

    def test_factura_allow_overrisk_company_no_bloquea(self):
        self.cliente.credit_limit = 1.0
        self.company.allow_overrisk_invoice_validation = True
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        inv.action_post()
        self.assertEqual(inv.state, "posted")
        self.company.allow_overrisk_invoice_validation = False

    def test_factura_proveedor_no_evaluada(self):
        # _first_invoice_exception_msg solo filtra move_type == out_invoice.
        self.cliente.credit_limit = 1.0
        bill = self.init_invoice(
            "in_invoice", partner=self.cliente, products=self.product_a
        )
        bill.action_post()
        self.assertEqual(bill.state, "posted")

    def test_factura_from_validate_move_wiz_lanza_validation_error(self):
        self.cliente.credit_limit = 1.0
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        with self.assertRaises(ValidationError):
            inv.with_context(from_validate_move_wiz=True).action_post()

    # ================================================================== #
    #  6. WIZARD DE OVERRIDE                                              #
    # ================================================================== #
    def test_wizard_can_authorize_vendedor_false(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.with_user(self.user_vendedor).action_confirm()
        wiz = self.env["polpo.credit.override.wiz"].browse(res["res_id"])
        self.assertFalse(wiz.with_user(self.user_vendedor).can_authorize)

    def test_wizard_can_authorize_autorizador_true(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        wiz = self.env["polpo.credit.override.wiz"].browse(res["res_id"])
        self.assertTrue(wiz.with_user(self.user_autorizador).can_authorize)

    def test_wizard_authorize_sin_permiso_lanza_accesserror(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        wiz = self.env["polpo.credit.override.wiz"].browse(res["res_id"])
        with self.assertRaises(AccessError):
            wiz.with_user(self.user_vendedor).button_authorize()
        # La orden sigue en draft.
        self.assertEqual(order.state, "draft")

    def test_wizard_authorize_confirma_orden_y_registra_override(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        # El wizard lo opera el autorizador: la ACL solo le da write a él.
        wiz = self.env["polpo.credit.override.wiz"].browse(
            res["res_id"]).with_user(self.user_autorizador)
        wiz.override_reason = "Cliente histórico, pago garantizado."
        wiz.button_authorize()
        # Orden confirmada con override registrado.
        self.assertEqual(order.state, "sale")
        self.assertTrue(order.credit_override_flag)
        self.assertEqual(order.credit_override_user_id, self.user_autorizador)
        self.assertEqual(
            order.credit_override_reason, "Cliente histórico, pago garantizado."
        )
        self.assertTrue(order.credit_override_date)

    def test_wizard_authorize_postea_factura(self):
        self.cliente.credit_limit = 1.0
        inv = self.init_invoice(
            "out_invoice", partner=self.cliente, products=self.product_a
        )
        res = inv.action_post()
        wiz = self.env["polpo.credit.override.wiz"].browse(
            res["res_id"]).with_user(self.user_autorizador)
        wiz.override_reason = "Excepción aprobada."
        wiz.button_authorize()
        self.assertEqual(inv.state, "posted")
        self.assertTrue(inv.credit_override_flag)
        self.assertEqual(inv.credit_override_user_id, self.user_autorizador)

    def test_wizard_authorize_registra_en_chatter(self):
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        wiz = self.env["polpo.credit.override.wiz"].browse(
            res["res_id"]).with_user(self.user_autorizador)
        msgs_antes = len(order.message_ids)
        wiz.override_reason = "Motivo X"
        wiz.button_authorize()
        self.assertGreater(len(order.message_ids), msgs_antes)
        ultimo = order.message_ids[0]
        self.assertIn("Autorización de excepción crediticia", ultimo.body)
        self.assertIn("Motivo X", ultimo.body)

    def test_wizard_authorize_sin_origen_no_falla(self):
        wiz = self.env["polpo.credit.override.wiz"].create({
            "partner_id": self.cliente.id,
            "exception_msg": "x",
            "continue_method": "action_confirm",
        })
        # origin_reference vacío -> retorna sin hacer nada (no error).
        self.assertFalse(
            wiz.with_user(self.user_autorizador).button_authorize()
        )

    def test_erp_manager_no_implica_autorizador(self):
        # CR-02: la autorización de crédito no se hereda de Ajustes
        # (erp_manager); se asigna explícitamente por usuario. En bases
        # actualizadas desde la versión con implied, este test falla hasta
        # aplicar la limpieza SQL de res_groups_implied_rel.
        self.assertNotIn(
            self.env.ref("polpo_credit_risk.group_credit_authorizer"),
            self.env.ref("base.group_erp_manager").implied_ids,
        )

    def test_wizard_authorize_metodo_fuera_de_allowlist_lanza_usererror(self):
        # CR-01: continue_method está allowlisteado por modelo. Un método
        # arbitrario (o el método válido del OTRO modelo) no se ejecuta.
        self.cliente.credit_limit = 10.0
        order = self._venta(amount=100.0)
        res = order.action_confirm()
        # Manipulación del continue_method por el propio autorizador (write
        # legítimo por ACL): la allowlist igual tiene que frenarlo.
        wiz = self.env["polpo.credit.override.wiz"].browse(
            res["res_id"]).with_user(self.user_autorizador)
        wiz.continue_method = "unlink"
        with self.assertRaises(UserError):
            wiz.button_authorize()
        wiz.continue_method = "action_post"  # válido, pero de account.move
        with self.assertRaises(UserError):
            wiz.button_authorize()
        self.assertEqual(order.state, "draft")

    def test_wizard_referencia_modelo_fuera_de_allowlist_no_asignable(self):
        # CR-01: el Reference solo admite sale.order / account.move; asignar
        # otro modelo falla en la validación del campo.
        with self.assertRaises(ValueError):
            self.env["polpo.credit.override.wiz"].create({
                "partner_id": self.cliente.id,
                "exception_msg": "x",
                "origin_reference": f"res.partner,{self.cliente.id}",
                "continue_method": "action_confirm",
            })

    def test_action_show_devuelve_accion_form(self):
        wiz = self.env["polpo.credit.override.wiz"].create({
            "partner_id": self.cliente.id,
            "exception_msg": "motivo",
            "continue_method": "action_confirm",
        })
        action = wiz.action_show()
        self.assertEqual(action["res_model"], "polpo.credit.override.wiz")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["res_id"], wiz.id)

    # ================================================================== #
    #  7. INTEGRACIÓN: riesgo total con venta real                       #
    # ================================================================== #
    def test_integracion_riesgo_total_con_venta_real(self):
        # Camino integral: límite bajo, venta confirmada eleva risk_sale_order,
        # nueva venta sobre el mismo cliente abre wizard al confirmar.
        self.cliente.credit_limit = 50.0
        self.cliente.risk_sale_order_include = True
        primera = self._venta(amount=100.0, confirm=True)
        self.assertEqual(primera.state, "sale")
        # Segunda venta: el cliente ya está en exception por la primera.
        segunda = self._venta(amount=100.0)
        res = segunda.action_confirm()
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "polpo.credit.override.wiz")

    # ================================================================== #
    #  8. RUBROS NEGATIVOS: no rebajan risk_total (corregido)            #
    # ================================================================== #
    def _stub_rubros(self, open_amount, account_amount):
        """Fija risk_invoice_open y risk_account_amount de forma estable
        sobreescribiendo su compute (revertido por patch al terminar)."""
        Partner = type(self.cliente)

        def stub_compute(records):
            for rec in records:
                rec.risk_invoice_draft = 0.0
                rec.risk_invoice_open = open_amount
                rec.risk_invoice_unpaid = 0.0
                rec.risk_account_amount = account_amount
                rec.risk_account_amount_unpaid = 0.0

        self.patch(Partner, "_compute_risk_account_amount", stub_compute)

    def test_rubro_negativo_no_rebaja_risk_total(self):
        """Un rubro incluido NEGATIVO ya no rebaja risk_total (fix 2026-07-10).

        _compute_risk_exception normaliza a 0 los rubros negativos al sumar.
        Construimos dos rubros incluidos: uno positivo grande y uno negativo
        (saldo a favor en 'otra cuenta'). El total suma solo la parte positiva,
        no la suma algebraica.
        """
        partner = self.cliente
        partner.credit_limit = 0.0
        partner.risk_invoice_open_include = True
        partner.risk_account_amount_include = True
        self._stub_rubros(open_amount=1000.0, account_amount=-400.0)
        partner.invalidate_recordset(
            ["risk_invoice_open", "risk_account_amount", "risk_total"]
        )
        # Fix: max(1000, 0) + max(-400, 0) = 1000; el negativo se pisa en 0.
        self.assertEqual(partner.risk_total, 1000.0)

    def test_rubro_negativo_no_enmascara_exceso(self):
        """Un saldo a favor en otra cuenta ya no oculta un exceso real.

        credit_limit=700. risk_invoice_open=1000 (excede), y un
        risk_account_amount=-400 que ANTES bajaba el total a 600 < 700 y
        ocultaba la excepción. Con el fix el negativo se normaliza a 0, el total
        queda en 1000 > 700 -> marca exception por límite global.
        """
        partner = self.cliente
        partner.credit_limit = 700.0
        partner.risk_invoice_open_include = True
        partner.risk_account_amount_include = True
        self._stub_rubros(open_amount=1000.0, account_amount=-400.0)
        partner.invalidate_recordset(
            ["risk_invoice_open", "risk_account_amount",
             "risk_total", "risk_exception"]
        )
        # 1000 > 700 -> excepción por límite global (el rubro negativo ya no enmascara).
        self.assertEqual(partner.risk_total, 1000.0)
        self.assertTrue(partner.risk_exception)
