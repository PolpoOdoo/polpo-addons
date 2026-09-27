# -*- coding: utf-8 -*-
"""Tests de qapps_cheque_info (models/account_payment.py).

Cubre las tres cosas que el módulo promete:

- el asistente de registro de pago traslada numero_cheque / vencimiento / note
  a los vals del pago (_create_payment_vals_from_wizard),
- al confirmar el pago, action_post estampa esos datos en las líneas del asiento
  del pago,
- un pago sin datos de cheque no escribe nada y, sobre todo, no borra los datos
  de cheque que ya tenía otro pago de la misma factura.

Además cubre el camino propio de Odoo 18: un pago cuyo método de pago no tiene
cuenta transitoria se confirma sin asiento (move_id vacío), y ahí no hay apunte
al que propagar.

Las fechas son relativas a hoy: un cheque diferido siempre vence en el futuro y
una fecha absoluta envejece el fixture.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestChequeInfo(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.partner_a
        # El diario de cheques es el estado en el que la funcionalidad se usa de
        # verdad: un banco propio, no el diario de banco que trae el plan.
        cls.journal_cheque = cls.env["account.journal"].create({
            "name": "Banco Cheques",
            "type": "bank",
            "code": "CHQI",
            "company_id": cls.company.id,
        })
        cls.vencimiento = fields.Date.context_today(cls.env.user) + timedelta(days=45)

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _factura(self):
        return self.init_invoice(
            "out_invoice", partner=self.partner, products=self.product_a, post=True,
        )

    def _wizard(self, invoice, **vals):
        vals.setdefault("journal_id", self.journal_cheque.id)
        return self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids,
        ).create(vals)

    # ------------------------------------------------------------------ #
    #  Registro de pago con datos de cheque                               #
    # ------------------------------------------------------------------ #
    def test_wizard_propaga_cheque_al_pago_y_a_los_apuntes(self):
        """Del asistente al pago y del pago a las líneas del asiento."""
        invoice = self._factura()
        wizard = self._wizard(
            invoice,
            numero_cheque="0001234",
            vencimiento=self.vencimiento,
            note="Cheque diferido recibido en mostrador",
        )

        # El asistente tiene que exponer los tres campos: si el módulo no los
        # agregó, create() ya habría fallado.
        self.assertEqual(wizard.numero_cheque, "0001234")

        payment = wizard._create_payments()
        self.assertEqual(len(payment), 1)

        # 1) Llegaron al pago.
        self.assertEqual(payment.numero_cheque, "0001234")
        self.assertEqual(payment.vencimiento, self.vencimiento)
        self.assertEqual(payment.note, "Cheque diferido recibido en mostrador")

        # 2) Llegaron a los apuntes del asiento del pago, a todos.
        self.assertTrue(payment.move_id, "el pago tiene que haber generado asiento")
        lineas = payment.move_id.line_ids
        self.assertTrue(lineas)
        for linea in lineas:
            self.assertEqual(linea.numero_cheque, "0001234")
            self.assertEqual(linea.vencimiento, self.vencimiento)
            self.assertEqual(linea.note, "Cheque diferido recibido en mostrador")

    def test_action_post_propaga_al_confirmar_el_pago_suelto(self):
        """Un pago creado a mano (sin factura) también estampa sus apuntes."""
        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner.id,
            "journal_id": self.journal_cheque.id,
            "amount": 333.34,
            "numero_cheque": "0009999",
            "vencimiento": self.vencimiento,
        })
        payment.action_post()

        self.assertTrue(payment.move_id)
        for linea in payment.move_id.line_ids:
            self.assertEqual(linea.numero_cheque, "0009999")
            self.assertEqual(linea.vencimiento, self.vencimiento)

    # ------------------------------------------------------------------ #
    #  Caso hermano: pago sin datos de cheque                             #
    # ------------------------------------------------------------------ #
    def test_pago_sin_datos_de_cheque_no_escribe_nada(self):
        """Sin numero, vencimiento ni observaciones no se estampa ningún apunte."""
        invoice = self._factura()
        payment = self._wizard(invoice)._create_payments()

        self.assertFalse(payment.numero_cheque)
        self.assertFalse(payment.vencimiento)
        self.assertFalse(payment.note)
        self.assertTrue(payment.move_id)
        for linea in payment.move_id.line_ids:
            self.assertFalse(linea.numero_cheque)
            self.assertFalse(linea.vencimiento)
            self.assertFalse(linea.note)
        # Tampoco quedó estampada la línea de la factura.
        for linea in invoice.line_ids:
            self.assertFalse(linea.numero_cheque)
            self.assertFalse(linea.vencimiento)

    def test_pago_sin_cheque_no_borra_el_cheque_del_pago_anterior(self):
        """Consecuencia grave y silenciosa: perder el cheque ya registrado.

        Una factura cobrada en dos partes, primero con cheque y después en
        efectivo. El segundo pago comparte grupo de conciliación con el primero,
        así que si la propagación se corriera después de conciliar, o si se
        escribiera sin mirar si hay datos, borraría el número y el vencimiento
        del cheque ya cobrado y nadie lo notaría hasta cerrar la cartera.
        """
        invoice = self._factura()
        total = invoice.amount_total

        con_cheque = self._wizard(
            invoice, amount=total / 2, numero_cheque="0005555",
            vencimiento=self.vencimiento,
        )._create_payments()
        estampadas = con_cheque.move_id.line_ids
        self.assertTrue(estampadas)

        efectivo = self._wizard(invoice, amount=total / 2)._create_payments()
        self.assertTrue(efectivo.move_id)

        # Las líneas del primer pago siguen con su cheque.
        for linea in estampadas:
            self.assertEqual(
                linea.numero_cheque, "0005555",
                "el segundo pago pisó el número de cheque del primero",
            )
            self.assertEqual(linea.vencimiento, self.vencimiento)

    # ------------------------------------------------------------------ #
    #  Camino propio de Odoo 18: pago confirmado sin asiento              #
    # ------------------------------------------------------------------ #
    def test_pago_sin_cuenta_transitoria_se_confirma_sin_asiento(self):
        """En Odoo 18 un pago sin outstanding_account_id no genera asiento.

        _generate_journal_entry() filtra por ese campo y _check_move_id() solo
        exige el asiento cuando la cuenta existe, así que el pago queda
        confirmado con move_id vacío. action_post no tiene que romper ni
        inventar apuntes. Es el estado que aparece en las bases con el módulo
        accounting instalado, donde create() no fuerza la cuenta transitoria.
        """
        self.journal_cheque.inbound_payment_method_line_ids.payment_account_id = False
        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.partner.id,
            "journal_id": self.journal_cheque.id,
            "amount": 500.0,
            "numero_cheque": "0007777",
            "vencimiento": self.vencimiento,
        })
        # create() de account fuerza la cuenta transitoria en Community para
        # garantizar el asiento; la sacamos para reproducir el caso de Enterprise.
        payment.outstanding_account_id = False
        self.assertFalse(payment.outstanding_account_id)

        payment.action_post()

        self.assertFalse(payment.move_id, "sin cuenta transitoria no hay asiento")
        self.assertIn(payment.state, ("in_process", "paid"))
        # El dato del cheque sigue en el pago, que es el único lugar donde puede estar.
        self.assertEqual(payment.numero_cheque, "0007777")
