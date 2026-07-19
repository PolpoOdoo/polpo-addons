# -*- coding: utf-8 -*-
"""Tests para qapps_check_wallet.

Cubre:
- El campo ``is_check_journal`` agregado a account.journal
  (models/account_journal.py) y su rol en el WHERE de la VIEW SQL.
- La VIEW SQL ``qapps.check.wallet`` (_auto=False) definida en
  models/qapps_check_wallet.py: que sea consultable (smoke), que su _order
  funcione, y que un cheque en cartera real aparezca con estado 'pending'.
- Métodos puros / de protección del modelo de la cartera:
  get_dashboard_totals, action_open_* y los action_create_* / action_*_collection
  que validan la selección antes de operar.

Convenciones: AccountTestInvoicingCommon (partner_a), data propia por test,
sin Form para campos fuera de vista, .sudo() donde aplique. No corre Odoo aquí.
"""
from odoo.tests import tagged
from odoo.exceptions import UserError

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestCheckWallet(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a
        cls.Wallet = cls.env["qapps.check.wallet"]

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    @classmethod
    def _crear_diario_cheques(cls):
        """Diario de cheques con método de pago 'Manual (entrante)' y una
        cuenta de cobros pendientes, marcado is_check_journal=True. Es la
        configuración que la VIEW exige para considerar una línea cheque en
        cartera."""
        cuenta_cartera = cls.env["account.account"].create({
            "name": "Cheques en cartera",
            "code": "CHQCART",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        diario = cls.env["account.journal"].create({
            "name": "Cheques recibidos",
            "type": "bank",
            "code": "CHWQ",
            "company_id": cls.company.id,
            "is_check_journal": True,
        })
        # La línea de método de pago manual entrante existe por defecto en los
        # diarios bancarios; le seteamos la cuenta de cobros pendientes.
        linea_manual = diario.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == "manual"
        )
        linea_manual.payment_account_id = cuenta_cartera.id
        # La cartera es una VIEW SQL (_auto=False) cuyo WHERE lee
        # account_payment_method_line.payment_account_id y
        # account_journal.is_check_journal. El ORM no sabe declarar esas
        # dependencias de flush para un modelo _auto=False, así que hay que
        # bajar estas escrituras a Postgres antes de consultar la VIEW.
        cls.env.flush_all()
        return diario, cuenta_cartera

    def _asentar_cheque_en_cartera(self, diario, cuenta_cartera, importe=1000.0):
        """Asiento posteado con un débito en la cuenta de cheques en cartera:
        replica el estado contable de un cheque recibido pendiente. Devuelve la
        línea de cheque (move.line) en la cuenta de cartera."""
        contrapartida = self.company_data["default_account_receivable"]
        move = self.env["account.move"].create({
            "journal_id": diario.id,
            "date": "2026-06-10",
            "line_ids": [
                (0, 0, {
                    "name": "Cheque cliente",
                    "account_id": cuenta_cartera.id,
                    "partner_id": self.partner.id,
                    "debit": importe,
                    "credit": 0.0,
                    "numero_cheque": "00012345",
                    "vencimiento": "2026-07-01",
                }),
                (0, 0, {
                    "name": "Contrapartida",
                    "account_id": contrapartida.id,
                    "partner_id": self.partner.id,
                    "debit": 0.0,
                    "credit": importe,
                }),
            ],
        })
        move.action_post()
        # Bajar el asiento (y sus líneas con numero_cheque/vencimiento) a
        # Postgres antes de leer la VIEW SQL de la cartera.
        self.env.flush_all()
        return move.line_ids.filtered(lambda l: l.account_id == cuenta_cartera)

    # ------------------------------------------------------------------ #
    #  is_check_journal                                                   #
    # ------------------------------------------------------------------ #
    def test_is_check_journal_default_false(self):
        diario = self.env["account.journal"].create({
            "name": "Banco normal",
            "type": "bank",
            "code": "BNKQ",
            "company_id": self.company.id,
        })
        self.assertFalse(diario.is_check_journal)

    def test_is_check_journal_se_puede_marcar(self):
        diario = self.env["account.journal"].create({
            "name": "Banco cheques",
            "type": "bank",
            "code": "BCHQ",
            "company_id": self.company.id,
            "is_check_journal": True,
        })
        self.assertTrue(diario.is_check_journal)

    # ------------------------------------------------------------------ #
    #  VIEW SQL: smoke / _order                                           #
    # ------------------------------------------------------------------ #
    def test_view_es_consultable(self):
        """Smoke: la VIEW SQL existe y se puede consultar sin error."""
        self.assertEqual(self.Wallet._auto, False)
        # No debe explotar aunque no haya filas.
        self.Wallet.search([], limit=1, order="id")

    def test_view_order_no_roto(self):
        """El _order del modelo usa due_date y payment_date, ambos campos
        reales de la VIEW; ordenar por _order no debe fallar."""
        self.assertEqual(self.Wallet._order, "due_date asc, payment_date asc")
        # Forzar el uso del _order por defecto (sin order explícito).
        self.Wallet.search([], limit=5)

    # ------------------------------------------------------------------ #
    #  VIEW SQL: contenido real                                           #
    # ------------------------------------------------------------------ #
    def test_cheque_en_cartera_aparece_pendiente(self):
        diario, cuenta = self._crear_diario_cheques()
        linea = self._asentar_cheque_en_cartera(diario, cuenta)

        registro = self.Wallet.search([("move_line_id", "=", linea.id)])
        self.assertEqual(len(registro), 1, "El cheque debe figurar en la cartera.")
        self.assertEqual(registro.state, "pending")
        self.assertEqual(registro.check_number, "00012345")
        self.assertEqual(registro.partner_id, self.partner)
        self.assertEqual(registro.journal_id, diario)
        self.assertAlmostEqual(registro.amount_company, 1000.0, places=2)

    def test_diario_no_cheque_no_aparece(self):
        """Si el diario NO tiene is_check_journal=True, su cuenta no entra al
        WHERE de la VIEW y el cheque no debe figurar en la cartera."""
        diario, cuenta = self._crear_diario_cheques()
        diario.is_check_journal = False
        linea = self._asentar_cheque_en_cartera(diario, cuenta)

        registro = self.Wallet.search([("move_line_id", "=", linea.id)])
        self.assertFalse(registro, "Sin is_check_journal el cheque no debe figurar.")

    # ------------------------------------------------------------------ #
    #  get_dashboard_totals                                               #
    # ------------------------------------------------------------------ #
    def test_dashboard_totals_estructura(self):
        totals = self.Wallet.get_dashboard_totals()
        for clave in (
            "pending_amount", "pending_count",
            "deposited_amount", "deposited_count",
            "at_collection_amount", "at_collection_count",
            "overdue_amount", "overdue_count",
            "total_count", "currency_id",
        ):
            self.assertIn(clave, totals)
        self.assertEqual(totals["currency_id"], self.company.currency_id.id)

    def test_dashboard_totals_cuenta_pendiente(self):
        diario, cuenta = self._crear_diario_cheques()
        self._asentar_cheque_en_cartera(diario, cuenta, importe=2500.0)

        totals = self.Wallet.get_dashboard_totals()
        self.assertGreaterEqual(totals["pending_count"], 1)
        self.assertGreaterEqual(totals["pending_amount"], 2500.0)
        self.assertGreaterEqual(totals["total_count"], 1)

    # ------------------------------------------------------------------ #
    #  action_open_* (registro real de la cartera)                        #
    # ------------------------------------------------------------------ #
    def test_action_open_move_devuelve_accion(self):
        diario, cuenta = self._crear_diario_cheques()
        linea = self._asentar_cheque_en_cartera(diario, cuenta)
        registro = self.Wallet.search([("move_line_id", "=", linea.id)])

        accion = registro.action_open_move()
        self.assertEqual(accion["res_model"], "account.move")
        self.assertEqual(accion["res_id"], registro.move_id.id)

    def test_action_open_deposit_sin_deposito_devuelve_false(self):
        diario, cuenta = self._crear_diario_cheques()
        linea = self._asentar_cheque_en_cartera(diario, cuenta)
        registro = self.Wallet.search([("move_line_id", "=", linea.id)])
        # Cheque pendiente: no tiene boleta/endoso/cobro asociado.
        self.assertFalse(registro.action_open_deposit())
        self.assertFalse(registro.action_open_endorsement())
        self.assertFalse(registro.action_open_collection())
        self.assertFalse(registro.action_open_payment())

    # ------------------------------------------------------------------ #
    #  Guardas de selección en los action_* de la cartera                 #
    # ------------------------------------------------------------------ #
    def test_create_endorsement_sin_pendientes_error(self):
        with self.assertRaises(UserError):
            self.Wallet.browse().action_create_endorsement()

    def test_create_collection_sin_pendientes_error(self):
        with self.assertRaises(UserError):
            self.Wallet.browse().action_create_collection()

    def test_credit_collection_sin_seleccion_error(self):
        with self.assertRaises(UserError):
            self.Wallet.browse().action_credit_collection()

    def test_reject_collection_sin_seleccion_error(self):
        with self.assertRaises(UserError):
            self.Wallet.browse().action_reject_collection()

    def test_create_endorsement_sobre_pendiente_real(self):
        """Sobre un cheque pendiente real, action_create_endorsement abre un
        form NUEVO (sin res_id) con el cheque, el diario y la moneda precargados
        en el contexto; partner_id lo completa el usuario. Al guardar con ese
        proveedor, el endoso queda en borrador con el cheque enganchado."""
        diario, cuenta = self._crear_diario_cheques()
        linea = self._asentar_cheque_en_cartera(diario, cuenta)
        registro = self.Wallet.search([("move_line_id", "=", linea.id)])

        accion = registro.action_create_endorsement()
        self.assertEqual(accion["res_model"], "qapps.check.endorsement")
        self.assertFalse(accion.get("res_id"), "Debe abrir un form nuevo, no un draft ya creado.")
        ctx = accion["context"]
        self.assertEqual(ctx["default_journal_id"], diario.id)
        self.assertEqual(ctx["default_check_payment_ids"], [(6, 0, linea.ids)])

        # El form, al completar partner_id (que el usuario elige) y guardar,
        # crea el endoso en borrador con el cheque enganchado.
        endoso = self.env["qapps.check.endorsement"].create({
            "journal_id": ctx["default_journal_id"],
            "currency_id": ctx["default_currency_id"],
            "check_payment_ids": ctx["default_check_payment_ids"],
            "partner_id": self.partner.id,
        })
        self.assertEqual(endoso.state, "draft")
        self.assertIn(linea, endoso.check_payment_ids)

    def test_create_collection_sobre_pendiente_real(self):
        """action_create_collection abre un form NUEVO con el cheque, diario y
        moneda precargados; bank_journal_id lo completa el usuario. Al guardar
        con ese banco, el envío queda en borrador con el cheque enganchado."""
        diario, cuenta = self._crear_diario_cheques()
        linea = self._asentar_cheque_en_cartera(diario, cuenta)
        registro = self.Wallet.search([("move_line_id", "=", linea.id)])

        accion = registro.action_create_collection()
        self.assertEqual(accion["res_model"], "qapps.check.collection")
        self.assertFalse(accion.get("res_id"), "Debe abrir un form nuevo, no un draft ya creado.")
        ctx = accion["context"]
        self.assertEqual(ctx["default_journal_id"], diario.id)
        self.assertEqual(ctx["default_check_payment_ids"], [(6, 0, linea.ids)])

        envio = self.env["qapps.check.collection"].create({
            "journal_id": ctx["default_journal_id"],
            "currency_id": ctx["default_currency_id"],
            "check_payment_ids": ctx["default_check_payment_ids"],
            "bank_journal_id": self.company_data["default_journal_bank"].id,
        })
        self.assertEqual(envio.state, "draft")
        self.assertIn(linea, envio.check_payment_ids)


@tagged("post_install", "-at_install")
class TestCheckCollectionAccount(AccountTestInvoicingCommon):
    """Tests del mapeo de cuentas por moneda (qapps.check.collection.account)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Mapping = cls.env["qapps.check.collection.account"]
        cls.cuenta_cobro = cls.env["account.account"].create({
            "name": "Cheques al cobro",
            "code": "CHQCOB",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        cls.cuenta_rech = cls.env["account.account"].create({
            "name": "Cheques rechazados",
            "code": "CHQRCH",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })

    def test_get_for_currency_sin_config_error(self):
        moneda = self.env["res.currency"].search([("name", "=", "CHF")], limit=1) \
            or self.env.ref("base.CHF")
        with self.assertRaises(UserError):
            self.Mapping._get_for_currency(self.company, moneda)

    def test_get_for_currency_con_config_devuelve_mapping(self):
        moneda = self.company.currency_id
        mapping = self.Mapping.create({
            "company_id": self.company.id,
            "currency_id": moneda.id,
            "collection_account_id": self.cuenta_cobro.id,
            "rejected_account_id": self.cuenta_rech.id,
        })
        encontrado = self.Mapping._get_for_currency(self.company, moneda)
        self.assertEqual(encontrado, mapping)
