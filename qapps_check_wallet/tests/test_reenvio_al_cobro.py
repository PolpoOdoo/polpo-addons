# -*- coding: utf-8 -*-
"""Un cheque no puede estar al cobro en dos envíos a la vez.

Caso de origen: cheques que ya estaban al cobro se agregaron a un envío
nuevo. El one2many ``check_payment_ids``
reasigna el ``check_collection_id`` del apunte, así que el envío nuevo le robó
los cheques al original: los envíos viejos quedaron vacíos y la acreditación
cortaba con "no se encontró la línea de cuenta puente", porque la línea puente
vive en el asiento del envío original y ``_get_bridge_line`` la buscaba por la
cuenta del envío actual.

El dominio del formulario ya excluía esos cheques y no alcanzó: el dominio
gobierna el diálogo de selección, no las escrituras. Por eso el invariante está
ahora en el modelo (guarda en ``account.move.line.write`` y validación en
``_check_before_validate``), la acreditación busca la línea puente en cualquier
envío y un envío no puede quedar en estado enviado sin asiento.

Los escenarios de dato ya roto se arman con SQL crudo a propósito: es la única
forma de reproducir el estado en el que quedó la base antes del arreglo, que es
lo que la acreditación tiene que poder resolver.
"""
from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestReenvioAlCobro(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a
        cls.moneda = cls.company.currency_id
        cls.Collection = cls.env["qapps.check.collection"]

        cls.cuenta_cartera = cls.env["account.account"].create({
            "name": "Cheques en cartera",
            "code": "CHQ885",
            "account_type": "asset_current",
            "company_id": cls.company.id,
        })
        cls.diario_cheques = cls.env["account.journal"].create({
            "name": "Cheques recibidos",
            "type": "bank",
            "code": "CHK885",
            "company_id": cls.company.id,
            "is_check_journal": True,
        })
        cls.diario_cheques.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == "manual"
        ).payment_account_id = cls.cuenta_cartera.id
        cls.banco_destino = cls.env["account.journal"].create({
            "name": "Banco destino",
            "type": "bank",
            "code": "BCO885",
            "company_id": cls.company.id,
            "bank_acc_number": "000188588885",
        })
        # Las cuentas puente tienen que ser conciliables: el circuito concilia
        # la línea de puente contra la de la acreditación o el rechazo.
        cls.cuenta_puente = cls.env["account.account"].create({
            "name": "Cheques al cobro",
            "code": "CHQCOB885",
            "account_type": "asset_current",
            "reconcile": True,
            "company_id": cls.company.id,
        })
        cls.cuenta_rechazo = cls.env["account.account"].create({
            "name": "Cheques rechazados",
            "code": "CHQREC885",
            "account_type": "asset_current",
            "reconcile": True,
            "company_id": cls.company.id,
        })
        cls.env["qapps.check.collection.account"].create({
            "company_id": cls.company.id,
            "currency_id": cls.moneda.id,
            "collection_account_id": cls.cuenta_puente.id,
            "rejected_account_id": cls.cuenta_rechazo.id,
        })
        cls.env.flush_all()

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _cheque_en_cartera(self, numero="885001", importe=1000.0):
        contra = self.company_data["default_account_receivable"]
        move = self.env["account.move"].create({
            "journal_id": self.diario_cheques.id,
            "date": "2026-06-10",
            "line_ids": [
                (0, 0, {
                    "name": "Cheque cliente",
                    "account_id": self.cuenta_cartera.id,
                    "partner_id": self.partner.id,
                    "debit": importe,
                    "credit": 0.0,
                    "numero_cheque": numero,
                    "vencimiento": "2026-07-01",
                }),
                (0, 0, {
                    "name": "Contrapartida",
                    "account_id": contra.id,
                    "partner_id": self.partner.id,
                    "debit": 0.0,
                    "credit": importe,
                }),
            ],
        })
        move.action_post()
        self.env.flush_all()
        return move.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_cartera)

    def _envio(self, lineas=None):
        vacio = self.env["account.move.line"]
        return self.Collection.create({
            "company_id": self.company.id,
            "journal_id": self.diario_cheques.id,
            "bank_journal_id": self.banco_destino.id,
            "currency_id": self.moneda.id,
            "check_payment_ids": [(6, 0, (lineas or vacio).ids)],
        })

    def _colgar_cheque_de(self, linea, envio):
        """Reproduce el dato roto: el apunte apunta a otro envío que no tiene su
        asiento. Va por SQL porque el ORM ahora lo impide, que es el arreglo."""
        self.env.cr.execute(
            "UPDATE account_move_line SET check_collection_id = %s WHERE id = %s",
            (envio.id, linea.id),
        )
        self.env.invalidate_all()

    # ------------------------------------------------------------------ #
    #  (a) No se puede reenviar al cobro un cheque que ya está al cobro    #
    # ------------------------------------------------------------------ #
    def test_agregar_cheque_ya_al_cobro_a_otro_envio_falla(self):
        """El síntoma del ticket: al guardar el envío nuevo, el one2many le
        robaba el cheque al envío original sin decir nada."""
        linea = self._cheque_en_cartera("885001")
        envio_a = self._envio(linea)
        envio_a.action_validate()

        with self.assertRaises(UserError) as err:
            self._envio(linea)
        mensaje = str(err.exception)
        self.assertIn(
            "885001", mensaje, "el error debe nombrar el número de cheque")
        self.assertIn(
            envio_a.name, mensaje,
            "el error debe nombrar el envío al cobro que ya tiene el cheque")
        # El envío original conserva su cheque.
        self.assertEqual(envio_a.check_payment_ids, linea)
        self.assertEqual(linea.check_collection_id, envio_a)

    def test_validar_envio_con_cheque_de_otro_envio_falla(self):
        """Defensa de segunda línea, para los envíos que ya quedaron mal
        armados en producción antes del arreglo: aunque el vínculo esté roto en
        la base, validar tiene que cortar nombrando el envío original."""
        linea = self._cheque_en_cartera("885002")
        envio_a = self._envio(linea)
        envio_a.action_validate()
        envio_b = self._envio()
        self._colgar_cheque_de(linea, envio_b)
        self.assertEqual(envio_b.check_payment_ids, linea)

        with self.assertRaises(UserError) as err:
            envio_b.action_validate()
        self.assertIn(envio_a.name, str(err.exception))
        self.assertEqual(envio_b.state, "draft")
        self.assertFalse(envio_b.move_id)

    def test_cheque_en_endoso_y_en_envio_al_cobro_falla(self):
        """Caso hermano: el mismo cheque reclamado por dos documentos de
        cartera distintos."""
        linea = self._cheque_en_cartera("885003")
        self.partner.supplier_rank = 1
        endoso = self.env["qapps.check.endorsement"].create({
            "company_id": self.company.id,
            "journal_id": self.diario_cheques.id,
            "currency_id": self.moneda.id,
            "partner_id": self.partner.id,
            "check_payment_ids": [(6, 0, linea.ids)],
        })
        self.assertEqual(linea.check_endorsement_id, endoso)
        with self.assertRaises(ValidationError):
            self._envio(linea)

    # ------------------------------------------------------------------ #
    #  (b) La acreditación encuentra la línea puente en el envío dueño     #
    # ------------------------------------------------------------------ #
    def test_acreditacion_con_el_vinculo_desactualizado(self):
        """Estado exacto de COB0099: el cheque cuelga de un envío sin asiento y
        su línea puente vive en el asiento del envío original. Antes del
        arreglo, acreditar cortaba con "no se encontró la línea de cuenta
        puente"."""
        linea = self._cheque_en_cartera("885004")
        envio_a = self._envio(linea)
        envio_a.action_validate()
        envio_b = self._envio()
        self._colgar_cheque_de(linea, envio_b)

        self.Collection._process_checks(linea, "credit")

        self.assertEqual(linea.check_collection_state, "credited")
        asiento = linea.collection_settle_move_id
        self.assertEqual(asiento.state, "posted")
        self.assertAlmostEqual(
            sum(asiento.line_ids.mapped("debit")),
            sum(asiento.line_ids.mapped("credit")), places=2,
            msg="el asiento de acreditación quedó descuadrado")
        # La línea puente del envío original quedó saldada.
        puente = envio_a.move_id.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_puente)
        self.assertTrue(
            puente.reconciled,
            "la acreditación debe conciliar la línea puente del envío original")
        # Y el cheque volvió al envío que lo contabilizó.
        self.assertEqual(
            linea.check_collection_id, envio_a,
            "el vínculo roto debe quedar corregido a favor del envío con asiento")
        self.assertFalse(envio_b.check_payment_ids)

    def test_rechazo_con_el_vinculo_desactualizado(self):
        linea = self._cheque_en_cartera("885005")
        envio_a = self._envio(linea)
        envio_a.action_validate()
        envio_b = self._envio()
        self._colgar_cheque_de(linea, envio_b)

        self.Collection._process_checks(linea, "reject")

        self.assertEqual(linea.check_collection_state, "rejected")
        self.assertEqual(linea.collection_settle_move_id.state, "posted")
        self.assertEqual(linea.check_collection_id, envio_a)

    def test_acreditacion_con_la_cuenta_puente_cambiada(self):
        """``collection_account_id`` es computado, no almacenado: si el mapeo
        por moneda cambia después del envío, el envío ya validado pasa a
        resolver una cuenta puente distinta de la que tiene su asiento. Ahí
        aparece el síntoma reportado, "no se encontró la línea de cuenta
        puente", y acreditar contra la cuenta nueva dejaría la vieja
        descuadrada."""
        linea = self._cheque_en_cartera("885012")
        envio = self._envio(linea)
        envio.action_validate()
        puente_original = envio.move_id.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_puente and l.debit > 0)

        otra_puente = self.env["account.account"].create({
            "name": "Cheques al cobro (nueva)",
            "code": "CHQCOB885B",
            "account_type": "asset_current",
            "reconcile": True,
            "company_id": self.company.id,
        })
        self.env["qapps.check.collection.account"].search([
            ("company_id", "=", self.company.id),
            ("currency_id", "=", self.moneda.id),
        ]).collection_account_id = otra_puente.id
        self.env.invalidate_all()
        self.assertEqual(
            envio.collection_account_id, otra_puente,
            "el envío ya validado resuelve ahora la cuenta puente nueva")

        self.Collection._process_checks(linea, "credit")

        self.assertEqual(linea.check_collection_state, "credited")
        self.assertTrue(
            puente_original.reconciled,
            "la acreditación debe saldar la línea puente que existe, no la que "
            "dicta el mapeo de hoy")
        self.assertNotIn(
            otra_puente, linea.collection_settle_move_id.line_ids.account_id,
            "acreditar contra la cuenta puente nueva dejaría la vieja abierta")

    def test_get_bridge_line_encuentra_la_linea_de_otro_envio(self):
        """El fallback puntual: sin él, el envío nuevo busca por su propia
        cuenta puente y no ve nada."""
        linea = self._cheque_en_cartera("885006")
        envio_a = self._envio(linea)
        envio_a.action_validate()
        envio_b = self._envio()

        puente = envio_b._get_bridge_line(linea)
        self.assertTrue(puente, "el fallback debe encontrar la línea puente")
        self.assertEqual(puente.move_id, envio_a.move_id)
        self.assertEqual(
            self.Collection._collection_of_bridge_line(puente), envio_a,
            "hay que poder identificar el envío dueño de la línea puente")

    def test_la_linea_de_banco_no_se_confunde_con_una_linea_puente(self):
        """collection_check_line_id marca también la línea de cartera del envío
        y las dos del asiento de acreditación. La de banco queda sin conciliar,
        así que buscar solo por ese campo devolvería una línea que no es el
        puente."""
        linea = self._cheque_en_cartera("885007")
        envio = self._envio(linea)
        envio.action_validate()
        self.Collection._process_checks(linea, "credit")

        self.assertFalse(
            self.Collection._get_open_bridge_line(linea),
            "acreditado el cheque no debe quedar ninguna línea puente abierta")

    # ------------------------------------------------------------------ #
    #  (c) Un envío enviado al cobro no puede quedarse sin asiento         #
    # ------------------------------------------------------------------ #
    def test_no_se_puede_marcar_enviado_sin_asiento(self):
        envio = self._envio(self._cheque_en_cartera("885008"))
        with self.assertRaises(ValidationError):
            envio.write({"state": "sent"})

    def test_no_se_puede_borrar_el_asiento_del_envio(self):
        """El asiento borrado a mano es lo que deja un envío en estado enviado y
        sin asiento: el ondelete por defecto ponía move_id en nulo sin avisar.

        Mientras el asiento está conciliado lo frena el propio core, pero la
        conciliación se puede deshacer desde la contabilidad; ahí la única
        defensa es el ondelete='restrict' de move_id."""
        linea = self._cheque_en_cartera("885009")
        envio = self._envio(linea)
        envio.action_validate()
        asiento = envio.move_id

        with self.assertRaises(UserError):
            asiento.with_context(force_delete=True).unlink()

        # Conciliación deshecha a mano: ahora el core deja borrar y solo queda
        # la clave foránea.
        asiento.line_ids.remove_move_reconcile()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                asiento.with_context(force_delete=True).unlink()
        self.env.invalidate_all()
        self.assertEqual(envio.state, "sent")
        self.assertEqual(envio.move_id, asiento)

    def test_volver_a_borrador_sigue_borrando_el_asiento(self):
        """El camino sancionado para deshacer un envío tiene que seguir
        funcionando con el ondelete en restrict."""
        linea = self._cheque_en_cartera("885010")
        envio = self._envio(linea)
        envio.action_validate()
        asiento = envio.move_id

        envio.action_back_to_draft()

        self.assertEqual(envio.state, "draft")
        self.assertFalse(envio.move_id)
        self.assertFalse(asiento.exists(), "el asiento de envío debe eliminarse")
        self.assertFalse(linea.check_collection_state)
        self.assertFalse(
            linea.reconciled, "el cheque debe volver a la cartera disponible")
        # Y el cheque se puede volver a enviar al cobro sin trabas.
        envio.action_validate()
        self.assertEqual(envio.state, "sent")

    # ------------------------------------------------------------------ #
    #  Sin regresión en el circuito normal                                #
    # ------------------------------------------------------------------ #
    def test_circuito_normal_sin_regresion(self):
        linea = self._cheque_en_cartera("885011")
        envio = self._envio(linea)
        envio.action_validate()
        self.assertEqual(envio.state, "sent")
        self.assertTrue(envio.move_id)
        self.assertEqual(linea.check_collection_state, "at_collection")

        self.Collection._process_checks(linea, "credit")
        self.assertEqual(linea.check_collection_state, "credited")
        self.assertEqual(
            linea.check_collection_id, envio,
            "el cheque no debe moverse de envío cuando el vínculo ya es correcto")
