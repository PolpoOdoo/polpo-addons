# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestRepostNoDuplica(AccountTestInvoicingCommon):
    """Regresion: resetear a borrador y re-postear una factura con retenciones
    NO debe crear un segundo asiento de reclasificacion.

    Antes del fix (guarda `and not move.reclass_retencion_move_id` en `_post`),
    el segundo action_post() volvia a llamar a
    `_create_retention_reclassification_entry()`, generando un asiento duplicado
    y re-reconciliando -> descuadre. Este test daria 2 asientos sin el fix y 1
    con el fix.
    """

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref)

        cls.iva_22 = cls.env["account.tax"].create({
            "name": "IVA 22% test",
            "amount_type": "percent",
            "amount": 22.0,
            "type_tax_use": "sale",
            "company_id": cls.company_data["company"].id,
        })

        cls.cuenta_retencion = cls.env["account.account"].create({
            "name": "Retenciones en garantia test",
            "code": "RETGAR9",
            "account_type": "liability_current",
            "company_id": cls.company_data["company"].id,
        })
        cls.company_data["company"].retention_warranty_account_id = cls.cuenta_retencion.id

        cls.Retencion = cls.env["qapps.retenciones.cce"]

    def _buscar_reclass(self, move):
        """Asientos de reclasificacion del partner/company de `move`.

        Se busca por prefijo de ref y move_type 'entry' (no por
        `ref == "Retenciones " + move.name`): en bases con qapps_efactura el
        nombre de la factura se reasigna despues de capturarse para el ref.
        """
        return self.env["account.move"].search([
            ("ref", "=like", "Retenciones %"),
            ("move_type", "=", "entry"),
            ("partner_id", "=", move.partner_id.id),
            ("company_id", "=", move.company_id.id),
        ])

    def test_repost_no_duplica_asiento_reclasificacion(self):
        move = self.init_invoice(
            "out_invoice",
            partner=self.partner_a,
            amounts=[1000.0],
            taxes=self.iva_22,
        )
        self.Retencion.create({
            "move_id": move.id,
            "application_type": "retention",
            "base_calculation": "base",
            "percentage": 10.0,
            "account_id": self.cuenta_retencion.id,
        })

        # Primer posteo: se crea exactamente 1 asiento de reclasificacion.
        move.action_post()
        self.assertTrue(move.reclass_retencion_move_id)
        reclass = self._buscar_reclass(move)
        self.assertEqual(len(reclass), 1)
        reclass_id = reclass.id

        # Reset a borrador + re-posteo: NO debe generar un segundo asiento.
        # La duplicacion solo es alcanzable en una factura AUN NO aprobada por
        # DGI: tras la aprobacion, qapps_efactura bloquea button_draft. Se limpia
        # la identidad CFE y se usa el contexto interno para reproducir el
        # reset+repost aislado del ciclo DGI.
        # Los campos de identidad CFE los aporta qapps_efactura; si el modulo no
        # esta instalado (test aislado) se omiten y el reset a borrador es el normal.
        cfe_reset = {"numero_cfe": False, "serie": False, "state_dgi": "draft"}
        move.sudo().write({k: v for k, v in cfe_reset.items() if k in move._fields})
        move.with_context(cfe_cancel_interno=True).button_draft()
        move.action_post()

        reclass_despues = self._buscar_reclass(move)
        self.assertEqual(
            len(reclass_despues), 1,
            "Re-postear no debe duplicar el asiento de reclasificacion",
        )
        self.assertEqual(
            reclass_despues.id, reclass_id,
            "Debe seguir siendo el mismo asiento de reclasificacion",
        )
        self.assertEqual(move.reclass_retencion_move_id.id, reclass_id)

    def test_repost_reconcilia_receivable_neto_de_retencion(self):
        # Bug #19: el reset a borrador rompe el reconcile entre el receivable de
        # la factura y el del asiento de reclasificacion (core:
        # button_draft -> remove_move_reconcile). El re-posteo preservaba el
        # asiento pero NO re-reconciliaba, dejando la cuenta corriente del cliente
        # con el importe COMPLETO en vez de neto de la retencion.
        # Factura 1000 + 22% IVA = 1220; retencion 10% de la base (1000) = 100.
        # El receivable neto debe ser 1220 - 100 = 1120, antes y despues del repost.
        move = self.init_invoice(
            "out_invoice",
            partner=self.partner_a,
            amounts=[1000.0],
            taxes=self.iva_22,
        )
        self.Retencion.create({
            "move_id": move.id,
            "application_type": "retention",
            "base_calculation": "base",
            "percentage": 10.0,
            "account_id": self.cuenta_retencion.id,
        })

        move.action_post()
        self.assertAlmostEqual(
            move.amount_residual, 1120.0, places=2,
            msg="Tras postear, el saldo debe quedar neto de la retencion (1120).",
        )

        cfe_reset = {"numero_cfe": False, "serie": False, "state_dgi": "draft"}
        move.sudo().write({k: v for k, v in cfe_reset.items() if k in move._fields})
        move.with_context(cfe_cancel_interno=True).button_draft()
        move.action_post()

        self.assertAlmostEqual(
            move.amount_residual, 1120.0, places=2,
            msg="Tras reset+repost el saldo debe volver a quedar neto (1120), no 1220.",
        )
        # El receivable del asiento de reclasificacion quedo reconciliado de nuevo.
        reclass = move.reclass_retencion_move_id
        reclass_receivable = reclass.line_ids.filtered(
            lambda l: l.account_id == move.line_ids.filtered(
                lambda x: x.account_type == "asset_receivable")[:1].account_id
        )
        self.assertTrue(
            all(l.reconciled for l in reclass_receivable),
            "El receivable del asiento de reclasificacion debe quedar reconciliado.",
        )

    def test_cancelar_factura_reversa_asiento_reclasificacion(self):
        # Bug #19 (cancel): al CANCELAR una factura con retenciones el asiento de
        # reclasificacion quedaba posteado y HUERFANO (sobrestimando la
        # contrapartida de la retencion). Ahora se reversa (net cero, conciliado
        # con su reversa) y se limpia el vinculo.
        move = self.init_invoice(
            "out_invoice",
            partner=self.partner_a,
            amounts=[1000.0],
            taxes=self.iva_22,
        )
        self.Retencion.create({
            "move_id": move.id,
            "application_type": "retention",
            "base_calculation": "base",
            "percentage": 10.0,
            "account_id": self.cuenta_retencion.id,
        })

        move.action_post()
        reclass = move.reclass_retencion_move_id
        self.assertTrue(reclass)
        self.assertEqual(reclass.state, "posted")

        cfe_reset = {"numero_cfe": False, "serie": False, "state_dgi": "draft"}
        move.sudo().write({k: v for k, v in cfe_reset.items() if k in move._fields})
        move.with_context(cfe_cancel_interno=True).button_cancel()

        self.assertEqual(move.state, "cancel")
        # El vinculo se limpio (un re-posteo generaria un asiento nuevo).
        self.assertFalse(move.reclass_retencion_move_id)
        # Se genero la reversa del asiento de reclasificacion.
        self.assertTrue(
            reclass.reversal_move_id,
            "El asiento de reclasificacion debe quedar reversado.",
        )
        # net cero: las lineas conciliables del asiento quedan conciliadas con la
        # reversa (sin residuo en cuentas abiertas).
        conciliables = reclass.line_ids.filtered(lambda l: l.account_id.reconcile)
        self.assertTrue(conciliables)
        self.assertTrue(
            all(l.reconciled for l in conciliables),
            "El asiento de reclasificacion debe conciliarse con su reversa.",
        )
