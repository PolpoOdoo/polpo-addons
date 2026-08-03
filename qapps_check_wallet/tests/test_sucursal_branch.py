# -*- coding: utf-8 -*-
"""Cheques operados desde una SUCURSAL (branch de Odoo 17).

En una jerarquía madre/sucursal los diarios bancarios y de cheques viven en la
compañía madre y las sucursales los comparten: el core lo habilita con
``account.journal._check_company_domain = check_company_domain_parent_of`` (ídem
``account.account``). El módulo lo estaba bloqueando por su cuenta con dominios
``('company_id', '=', company_id)``, así que parado en la sucursal el
desplegable "Banco destino" quedaba vacío y no se podía enviar cheques al cobro.

Segundo bloqueo, más abajo: el mapeo de cuentas puente por moneda
(qapps.check.collection.account) se buscaba con company_id exacto; con el mapeo
configurado en la madre, validar desde la sucursal cortaba con "No hay cuenta de
cheques al cobro configurada".

Cubre los dominios de UI tal como los evalúa el cliente web (safe_eval con el
company_id del registro), la resolución del mapeo de cuentas y el circuito
completo de envío al cobro desde la sucursal. El último test fija la ausencia de
regresión en clientes mono-compañía, que son la mayoría.
"""
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestCheckWalletSucursal(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matriz = cls.env.company
        cls.sucursal = cls.env["res.company"].create({
            "name": "Sucursal (branch)",
            "parent_id": cls.matriz.id,
            "currency_id": cls.matriz.currency_id.id,
        })
        cls.env.user.company_ids |= cls.sucursal
        cls.partner = cls.partner_a
        cls.moneda = cls.matriz.currency_id

        # Toda la infraestructura bancaria vive en la MADRE: es justamente el
        # escenario del ticket.
        cls.cuenta_cartera = cls.env["account.account"].create({
            "name": "Cheques en cartera",
            "code": "CHQBR",
            "account_type": "asset_current",
            "company_id": cls.matriz.id,
        })
        cls.diario_cheques = cls.env["account.journal"].create({
            "name": "Cheques recibidos",
            "type": "bank",
            "code": "CHKBR",
            "company_id": cls.matriz.id,
            "is_check_journal": True,
        })
        cls.diario_cheques.inbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == "manual"
        ).payment_account_id = cls.cuenta_cartera.id
        cls.banco_destino = cls.env["account.journal"].create({
            "name": "Banco destino",
            "type": "bank",
            "code": "BCOBR",
            "company_id": cls.matriz.id,
            "bank_acc_number": "000123456789",
        })

        # Las cuentas puente tienen que ser conciliables: el circuito concilia
        # la línea de puente del envío contra la de la acreditación / rechazo.
        cls.cuenta_puente = cls.env["account.account"].create({
            "name": "Cheques al cobro",
            "code": "CHQCOB",
            "account_type": "asset_current",
            "reconcile": True,
            "company_id": cls.matriz.id,
        })
        cls.cuenta_rechazo = cls.env["account.account"].create({
            "name": "Cheques rechazados",
            "code": "CHQREC",
            "account_type": "asset_current",
            "reconcile": True,
            "company_id": cls.matriz.id,
        })
        cls.mapeo_matriz = cls.env["qapps.check.collection.account"].create({
            "company_id": cls.matriz.id,
            "currency_id": cls.moneda.id,
            "collection_account_id": cls.cuenta_puente.id,
            "rejected_account_id": cls.cuenta_rechazo.id,
        })

        # Compañía de otra rama (independiente, con su propio plan de cuentas)
        # para verificar que el dominio no se abre de más.
        cls.otra_rama = cls.setup_company_data("Otra rama")["company"]
        cls.diario_ajeno = cls.env["account.journal"].create({
            "name": "Cheques ajenos",
            "type": "bank",
            "code": "CHKAJ",
            "company_id": cls.otra_rama.id,
            "is_check_journal": True,
        })
        cls.env.flush_all()

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _dominio_de(self, modelo, campo, company):
        """Evalúa el dominio declarado en el campo igual que el cliente web:
        con el company_id del registro en el contexto de evaluación."""
        dominio = self.env[modelo]._fields[campo].domain
        return safe_eval(dominio, {"company_id": company.id})

    def _cheque_en_cartera_de_la_sucursal(self, importe=1000.0):
        """Cheque recibido operando parado en la sucursal, con el diario de
        cheques de la madre. El asiento debe quedar en la sucursal."""
        contra = self.company_data["default_account_receivable"]
        move = self.env["account.move"].with_company(self.sucursal).create({
            "journal_id": self.diario_cheques.id,
            "date": "2026-06-10",
            "line_ids": [
                (0, 0, {
                    "name": "Cheque cliente",
                    "account_id": self.cuenta_cartera.id,
                    "partner_id": self.partner.id,
                    "debit": importe,
                    "credit": 0.0,
                    "numero_cheque": "BR000001",
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
        self.assertEqual(
            move.company_id, self.sucursal,
            "el asiento hecho desde la sucursal con el diario de la madre debe "
            "quedar en la sucursal")
        return move.line_ids.filtered(
            lambda l: l.account_id == self.cuenta_cartera)

    # ------------------------------------------------------------------ #
    #  Dominios de UI (lo que el usuario ve en el desplegable)            #
    # ------------------------------------------------------------------ #
    def test_dominio_diario_cheques_incluye_el_de_la_madre(self):
        dominio = self._dominio_de(
            "qapps.check.collection", "journal_id", self.sucursal)
        diarios = self.env["account.journal"].search(dominio)
        self.assertIn(
            self.diario_cheques, diarios,
            "parado en la sucursal, el diario de cheques de la madre debe "
            "poder elegirse")

    def test_dominio_banco_destino_incluye_el_de_la_madre(self):
        dominio = self._dominio_de(
            "qapps.check.collection", "bank_journal_id", self.sucursal)
        diarios = self.env["account.journal"].search(dominio)
        self.assertIn(
            self.banco_destino, diarios,
            'el desplegable "Banco destino" quedaba vacío en la sucursal: '
            "es el síntoma reportado en el ticket")

    def test_dominio_diario_endoso_incluye_el_de_la_madre(self):
        dominio = self._dominio_de(
            "qapps.check.endorsement", "journal_id", self.sucursal)
        diarios = self.env["account.journal"].search(dominio)
        self.assertIn(
            self.diario_cheques, diarios,
            "el endoso tiene el mismo bloqueo que el envío al cobro")

    def test_dominio_no_expone_diarios_de_otra_rama(self):
        """parent_of sube por la jerarquía, no baja ni cruza: una compañía
        hermana no debe aparecer en el desplegable de la sucursal."""
        dominio = self._dominio_de(
            "qapps.check.collection", "journal_id", self.sucursal)
        diarios = self.env["account.journal"].search(dominio)
        self.assertNotIn(
            self.diario_ajeno, diarios,
            "el dominio no debe abrirse a compañías fuera de la rama")

    # ------------------------------------------------------------------ #
    #  Mapeo de cuentas puente por moneda                                 #
    # ------------------------------------------------------------------ #
    def test_mapeo_de_cuentas_se_hereda_de_la_madre(self):
        Mapeo = self.env["qapps.check.collection.account"]
        self.assertEqual(
            Mapeo._find_mapping(self.sucursal, self.moneda), self.mapeo_matriz,
            "la sucursal debe usar el mapeo de cuentas de la madre en lugar de "
            "exigir uno duplicado")

    def test_mapeo_propio_de_la_sucursal_gana_sobre_el_de_la_madre(self):
        # La cuenta es de la madre a propósito: una branch usa el plan de
        # cuentas de la raíz, lo que puede diferir es a qué cuenta mapea.
        otra_cuenta = self.env["account.account"].create({
            "name": "Cheques al cobro (variante)",
            "code": "CHQCOB2",
            "account_type": "asset_current",
            "company_id": self.matriz.id,
        })
        mapeo_sucursal = self.env["qapps.check.collection.account"].create({
            "company_id": self.sucursal.id,
            "currency_id": self.moneda.id,
            "collection_account_id": otra_cuenta.id,
            "rejected_account_id": otra_cuenta.id,
        })
        Mapeo = self.env["qapps.check.collection.account"]
        self.assertEqual(
            Mapeo._find_mapping(self.sucursal, self.moneda), mapeo_sucursal,
            "si la sucursal tiene su propia configuración, esa gana")
        self.assertEqual(
            Mapeo._find_mapping(self.matriz, self.moneda), self.mapeo_matriz,
            "la madre no debe verse afectada por la configuración de la hija")

    def test_mapeo_visible_con_solo_la_sucursal_seleccionada(self):
        """El dominio con parent_of no alcanza si la ir.rule del propio módulo
        filtra por 'in company_ids': un usuario parado únicamente en la sucursal
        no vería el mapeo de la madre y el envío al cobro volvería a cortar al
        validar. La regla acompaña a las del core para account.journal y
        account.account, que son parent_of."""
        usuario = self.env["res.users"].create({
            "name": "Contadora de la sucursal",
            "login": "sucursal_contadora",
            "company_id": self.sucursal.id,
            "company_ids": [(6, 0, (self.matriz + self.sucursal).ids)],
            "groups_id": [(4, self.env.ref("account.group_account_invoice").id)],
        })
        Mapeo = (
            self.env["qapps.check.collection.account"]
            .with_user(usuario)
            .with_context(allowed_company_ids=[self.sucursal.id])
        )
        self.assertEqual(
            Mapeo._find_mapping(self.sucursal, self.moneda), self.mapeo_matriz,
            "parado solo en la sucursal, la ir.rule debe dejar leer el mapeo de "
            "la madre")

    def test_mapeo_mono_compania_sin_regresion(self):
        """El caso de la enorme mayoría de los clientes: una sola compañía, sin
        padre. parent_of sobre una compañía sin ancestros devuelve esa misma
        compañía, así que el comportamiento no cambia."""
        Mapeo = self.env["qapps.check.collection.account"]
        self.assertEqual(
            Mapeo._find_mapping(self.matriz, self.moneda), self.mapeo_matriz)
        self.assertFalse(
            Mapeo._find_mapping(self.matriz, self.currency_data["currency"]),
            "sin mapeo para esa moneda debe devolver vacío, no otro registro")

    # ------------------------------------------------------------------ #
    #  El documento sigue a los cheques, no a la compañía activa           #
    # ------------------------------------------------------------------ #
    def test_envio_al_cobro_hereda_la_compania_del_cheque(self):
        """Julio operaba parado en la madre como workaround. Si los cheques son
        de la sucursal, el documento tiene que nacer en la sucursal: si nacía en
        la madre, conciliar sus líneas contra las del cheque falla por compañías
        distintas."""
        linea = self._cheque_en_cartera_de_la_sucursal()
        # Parado en la madre con la sucursal también seleccionada: es la única
        # forma de ver los cheques de la sucursal desde la madre, porque la
        # cartera es un listado de documentos y su ir.rule filtra por
        # company_ids (a diferencia del mapeo de cuentas, que es configuración).
        cartera = self.env["qapps.check.wallet"].with_context(
            allowed_company_ids=[self.matriz.id, self.sucursal.id]
        ).with_company(self.matriz).search([("move_line_id", "=", linea.id)])
        self.assertTrue(cartera, "el cheque de la sucursal debe verse en la cartera")
        accion = cartera.action_create_collection()
        self.assertEqual(
            accion["context"]["default_company_id"], self.sucursal.id,
            "el envío al cobro debe crearse en la compañía del cheque")

    # ------------------------------------------------------------------ #
    #  Circuito completo desde la sucursal                                #
    # ------------------------------------------------------------------ #
    def test_envio_al_cobro_desde_la_sucursal(self):
        linea = self._cheque_en_cartera_de_la_sucursal()
        envio = self.env["qapps.check.collection"].with_company(
            self.sucursal
        ).create({
            "company_id": self.sucursal.id,
            "journal_id": self.diario_cheques.id,
            "bank_journal_id": self.banco_destino.id,
            "currency_id": self.moneda.id,
            "check_payment_ids": [(6, 0, linea.ids)],
        })
        self.assertEqual(
            envio.collection_account_id, self.cuenta_puente,
            "el envío de la sucursal debe resolver la cuenta puente de la madre")

        envio.action_validate()

        self.assertEqual(envio.state, "sent")
        self.assertEqual(
            envio.move_id.company_id, self.sucursal,
            "el asiento de envío al cobro queda en la sucursal, no en la madre")
        self.assertAlmostEqual(
            sum(envio.move_id.line_ids.mapped("debit")),
            sum(envio.move_id.line_ids.mapped("credit")), places=2,
            msg="el asiento de envío al cobro quedó descuadrado")
        self.assertTrue(
            linea.reconciled,
            "el cheque debe salir de la cartera al enviarse al cobro")
        self.assertEqual(linea.check_collection_state, "at_collection")

    def test_acreditacion_desde_la_sucursal(self):
        linea = self._cheque_en_cartera_de_la_sucursal()
        envio = self.env["qapps.check.collection"].with_company(
            self.sucursal
        ).create({
            "company_id": self.sucursal.id,
            "journal_id": self.diario_cheques.id,
            "bank_journal_id": self.banco_destino.id,
            "currency_id": self.moneda.id,
            "check_payment_ids": [(6, 0, linea.ids)],
        })
        envio.action_validate()

        self.env["qapps.check.collection"]._process_checks(linea, "credit")

        self.assertEqual(linea.check_collection_state, "credited")
        asiento = linea.collection_settle_move_id
        self.assertEqual(
            asiento.company_id, self.sucursal,
            "la acreditación con el banco de la madre debe asentarse en la sucursal")
        self.assertEqual(asiento.state, "posted")

    # ------------------------------------------------------------------ #
    #  Referencia de boleta compartida entre envíos (devolución Yanela)   #
    # ------------------------------------------------------------------ #
    def test_referencia_de_boleta_relaciona_envios_de_ambas_companias(self):
        """La boleta bancaria es una sola pero en Odoo van dos envíos (uno por
        compañía): la misma referencia debe dejarlos filtrables y agrupables
        juntos, y debe poder cargarse con el envío ya validado."""
        Collection = self.env["qapps.check.collection"]
        vals_comunes = {
            "journal_id": self.diario_cheques.id,
            "bank_journal_id": self.banco_destino.id,
            "currency_id": self.moneda.id,
            "boleta_ref": "BOL-0001",
        }
        envio_matriz = Collection.with_company(self.matriz).create(
            dict(vals_comunes, company_id=self.matriz.id)
        )
        envio_sucursal = Collection.with_company(self.sucursal).create(
            dict(vals_comunes, company_id=self.sucursal.id)
        )
        encontrados = Collection.with_context(
            allowed_company_ids=[self.matriz.id, self.sucursal.id]
        ).search([("boleta_ref", "=", "BOL-0001")])
        self.assertEqual(
            encontrados, envio_matriz | envio_sucursal,
            "la misma referencia debe relacionar los envíos de las dos compañías")
        # Editable con el envío validado (el número puede llegar después) y
        # sin viajar en un duplicado (copy=False).
        envio_matriz.boleta_ref = "BOL-0002"
        self.assertEqual(envio_matriz.boleta_ref, "BOL-0002")
        self.assertFalse(envio_matriz.copy_data()[0].get("boleta_ref"))
