# -*- coding: utf-8 -*-
"""Tests para qapps_current_rate_uy.

Cubre la obtención de cotizaciones desde el web service del BCU:
  - parseo de una respuesta de ejemplo (stub),
  - creación de res.currency.rate con el valor correcto por moneda,
  - manejo de respuesta vacía / sin tasas,
  - lógica de exchange_task (decisión de actualizar según fecha de cierre).

CRÍTICO: nunca se llama al web service real. Se mockea zeep.Client
(importado como `Client` en el módulo res_currency) para que ni exchange_task
ni update_currency_rates abran una conexión SOAP.

Convenciones: monedas descartables (códigos inexistentes en la base) para no
chocar con tasas reales del entorno; cada test arma su propia data.
"""

from datetime import date
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

# Ruta del símbolo a parchear: el módulo hace `from zeep import Client`,
# por lo que se parchea el nombre tal como vive en res_currency.
CLIENT_PATH = 'odoo.addons.qapps_current_rate_uy.models.res_currency.Client'


class DatoCotizacion(dict):
    """Item de cotización al estilo zeep.

    El código accede por clave (``x['CodigoISO']``, ``x['TCC']``, ``x['Fecha']``),
    por lo que un dict alcanza para reproducir el comportamiento.
    """
    pass


class RespuestaCotizaciones(object):
    """Reproduce la respuesta del servicio de cotizaciones del BCU.

    El código real hace:
        response.datoscotizaciones['datoscotizaciones.dato']
    es decir: acceso por atributo a ``datoscotizaciones`` y luego por clave.
    """

    def __init__(self, datos):
        # ``datos`` = lista de DatoCotizacion (o None / [] para casos vacíos).
        self.datoscotizaciones = {'datoscotizaciones.dato': datos}


def _build_zeep_mock(last_update, datos):
    """Construye un mock de zeep.Client.

    El módulo instancia ``Client(wsdl)`` dos veces:
      1) servicio de última fecha de cierre -> Execute() devuelve last_update
      2) servicio de cotizaciones           -> Execute({...}) devuelve la respuesta

    Se distingue por la presencia de argumentos en la llamada a Execute():
    fecha de cierre se llama sin args; cotizaciones con un dict de parámetros.
    """
    def execute(*args, **kwargs):
        if args or kwargs:
            # Llamada al servicio de cotizaciones.
            return RespuestaCotizaciones(datos)
        # Llamada al servicio de última fecha de cierre.
        return last_update

    def client_factory(wsdl):
        cli = MagicMock(name='ZeepClient(%s)' % wsdl)
        cli.service.Execute.side_effect = execute
        return cli

    return client_factory


@tagged('post_install', '-at_install')
class TestCurrentRateUy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Currency = cls.env['res.currency']
        cls.Rate = cls.env['res.currency.rate']
        cls.IrConfig = cls.env['ir.config_parameter'].sudo()

        # Habilitar la actualización automática para que exchange_task no corte
        # en el primer chequeo.
        cls.IrConfig.set_param('qapps.currency_cotizacion_moneda', '1')
        cls.IrConfig.set_param('qapps.currency_servicio_fecha_cierre',
                               'https://fake/cierre?wsdl')
        cls.IrConfig.set_param('qapps.currency_servicio_cotizacion',
                               'https://fake/cotizacion?wsdl')
        cls.IrConfig.set_param('qapps.currency_email_notif', 'test@qapps.io')

        cls.fecha_cierre = date.today()

    # ------------------------------------------------------------------ #
    # Helpers de data
    # ------------------------------------------------------------------ #
    def _crear_moneda(self, name):
        """Crea (o reutiliza) una moneda descartable con código `name`.

        Se usan códigos que no existen de fábrica para no chocar con USD/EUR
        reales del entorno cuando hace falta aislamiento.
        """
        existente = self.Currency.with_context(active_test=False).search(
            [('name', '=', name)], limit=1)
        if existente:
            existente.active = True
            return existente
        # res.currency.symbol es required=True en el core de Odoo
        # (NotNullViolation si se omite); se usa el propio código como símbolo.
        return self.Currency.create({'name': name, 'symbol': name, 'active': True})

    def _dato(self, iso, tcc, fecha=None):
        return DatoCotizacion({
            'CodigoISO': iso,
            'TCC': tcc,
            'Fecha': fecha or self.fecha_cierre,
        })

    # ------------------------------------------------------------------ #
    # Parseo + creación de tasas (update_currency_rates)
    # ------------------------------------------------------------------ #
    def test_parseo_y_creacion_usd(self):
        """USD: rate = 1/TCC, una res.currency.rate por compañía raíz."""
        usd = self._crear_moneda('USD')
        datos = [self._dato('USD', 40.0)]

        empresas = self.env['res.company'].search(
            [('active', '=', True), ('parent_id', '=', False)])

        antes = self.Rate.search_count([('currency_id', '=', usd.id)])

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            usd.update_currency_rates(usd, self.fecha_cierre)

        creadas = self.Rate.search([
            ('currency_id', '=', usd.id),
            ('name', '=', self.fecha_cierre),
        ])
        # Una tasa por empresa raíz.
        self.assertEqual(len(creadas), len(empresas))
        self.assertEqual(self.Rate.search_count([('currency_id', '=', usd.id)]),
                         antes + len(empresas))
        # rate = 1 / TCC = 1 / 40 = 0.025
        self.assertAlmostEqual(creadas[0].rate, 1.0 / 40.0, places=9)

    def test_parseo_eur_invierte_tcc(self):
        """EUR: ISO esperado 'EURO', rate = 1/TCC."""
        eur = self._crear_moneda('EUR')
        datos = [self._dato('EURO', 45.0)]

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            eur.update_currency_rates(eur, self.fecha_cierre)

        creadas = self.Rate.search([
            ('currency_id', '=', eur.id),
            ('name', '=', self.fecha_cierre),
        ])
        self.assertTrue(creadas)
        self.assertAlmostEqual(creadas[0].rate, 1.0 / 45.0, places=9)

    def test_parseo_ui_usa_tcc_directo(self):
        """UYI: ISO esperado 'U.I.', rate = TCC directo (no se invierte).

        v18: la Unidad Indexada uruguaya pasó de 'UI' a 'UYI' en res.currency.
        """
        ui = self._crear_moneda('UYI')
        datos = [self._dato('U.I.', 5.5)]

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            ui.update_currency_rates(ui, self.fecha_cierre)

        creadas = self.Rate.search([
            ('currency_id', '=', ui.id),
            ('name', '=', self.fecha_cierre),
        ])
        self.assertTrue(creadas)
        # UI usa el TCC directo.
        self.assertAlmostEqual(creadas[0].rate, 5.5, places=9)

    def test_moneda_sin_match_no_crea_tasa(self):
        """Si el ISO de la moneda no está en la respuesta, no se crea tasa."""
        xtest = self._crear_moneda('XYZ')
        # La respuesta trae USD pero no XYZ.
        datos = [self._dato('USD', 40.0)]

        antes = self.Rate.search_count([('currency_id', '=', xtest.id)])

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            xtest.update_currency_rates(xtest, self.fecha_cierre)

        self.assertEqual(self.Rate.search_count([('currency_id', '=', xtest.id)]),
                         antes)

    def test_multiples_monedas_en_una_respuesta(self):
        """Una respuesta con USD, EUR y UYI crea las tres tasas correctamente."""
        usd = self._crear_moneda('USD')
        eur = self._crear_moneda('EUR')
        ui = self._crear_moneda('UYI')  # v18: la UI uruguaya es 'UYI'
        currencies = usd | eur | ui

        datos = [
            self._dato('USD', 40.0),
            self._dato('EURO', 45.0),
            self._dato('U.I.', 5.5),
        ]

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            usd.update_currency_rates(currencies, self.fecha_cierre)

        r_usd = self.Rate.search([('currency_id', '=', usd.id),
                                  ('name', '=', self.fecha_cierre)], limit=1)
        r_eur = self.Rate.search([('currency_id', '=', eur.id),
                                  ('name', '=', self.fecha_cierre)], limit=1)
        r_ui = self.Rate.search([('currency_id', '=', ui.id),
                                 ('name', '=', self.fecha_cierre)], limit=1)

        self.assertAlmostEqual(r_usd.rate, 1.0 / 40.0, places=9)
        self.assertAlmostEqual(r_eur.rate, 1.0 / 45.0, places=9)
        self.assertAlmostEqual(r_ui.rate, 5.5, places=9)

    # ------------------------------------------------------------------ #
    # Respuesta vacía / sin tasas
    # ------------------------------------------------------------------ #
    def test_respuesta_sin_tasas_envia_mail_y_no_crea(self):
        """rates == [] -> envía mail de aviso y no crea ninguna tasa."""
        usd = self._crear_moneda('USD')
        antes = self.Rate.search_count([('currency_id', '=', usd.id)])

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, [])):
            with patch.object(
                type(self.env['res.currency']), 'send_email_missing_rate'
            ) as mock_mail:
                usd.update_currency_rates(usd, self.fecha_cierre)

        mock_mail.assert_called_once_with(False)
        self.assertEqual(self.Rate.search_count([('currency_id', '=', usd.id)]),
                         antes)

    # ------------------------------------------------------------------ #
    # exchange_task (entry point del cron)
    # ------------------------------------------------------------------ #
    def test_exchange_task_desactivado_es_noop(self):
        """Sin el parámetro de actualización, exchange_task no hace nada."""
        self.IrConfig.set_param('qapps.currency_cotizacion_moneda', '')
        try:
            # No debe siquiera instanciar el cliente; si lo hiciera, el mock
            # lo registraría. Usamos un mock que falla si se llama Execute
            # del servicio de cierre.
            with patch(CLIENT_PATH) as mock_client:
                res = self.Currency.exchange_task()
            self.assertTrue(res)
            mock_client.assert_not_called()
        finally:
            self.IrConfig.set_param('qapps.currency_cotizacion_moneda', '1')

    def test_exchange_task_actualiza_si_usd_desactualizado(self):
        """USD sin fecha -> exchange_task dispara update_currency_rates."""
        self._crear_moneda('USD')
        datos = [self._dato('USD', 40.0)]

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, datos)):
            with patch.object(
                type(self.env['res.currency']), 'update_currency_rates'
            ) as mock_upd:
                self.Currency.exchange_task()

        mock_upd.assert_called_once()
        # last_update == fecha de cierre del servicio. Según cómo bindee el
        # registry el mock, puede llegar posicional (con o sin self) o kwarg:
        # buscarla en el call completo en vez de asumir la posición.
        call = mock_upd.call_args
        recibidos = list(call.args) + list(call.kwargs.values())
        self.assertIn(self.fecha_cierre, recibidos,
            "update_currency_rates no recibió la fecha de cierre del servicio")

    def test_exchange_task_no_actualiza_si_usd_al_dia(self):
        """Si USD ya tiene fecha >= fecha de cierre, no se actualiza."""
        usd = self._crear_moneda('USD')
        # Cargar una tasa con la misma fecha de cierre que devolverá el servicio.
        self.Rate.create({
            'currency_id': usd.id,
            'name': self.fecha_cierre,
            'rate': 0.025,
            'company_id': self.env.company.id,
        })

        with patch(CLIENT_PATH, side_effect=_build_zeep_mock(self.fecha_cierre, [self._dato('USD', 40.0)])):
            with patch.object(
                type(self.env['res.currency']), 'update_currency_rates'
            ) as mock_upd:
                res = self.Currency.exchange_task()

        mock_upd.assert_not_called()
        self.assertTrue(res)

    # ------------------------------------------------------------------ #
    # Notificación por email
    # ------------------------------------------------------------------ #
    def test_send_email_missing_rate_sin_moneda(self):
        """send_email_missing_rate(False) crea un mail.mail con el asunto global."""
        Mail = self.env['mail.mail']
        antes = Mail.search([], order='id desc', limit=1)
        antes_id = antes.id if antes else 0

        self.Currency.send_email_missing_rate(False)

        nuevo = Mail.search([('id', '>', antes_id)], order='id desc', limit=1)
        self.assertTrue(nuevo)
        self.assertIn('tasa de cambio del día', nuevo.subject)
        self.assertEqual(nuevo.email_to, 'test@qapps.io')

    def test_send_email_missing_rate_con_moneda(self):
        """send_email_missing_rate('USD') incluye el nombre de la moneda."""
        Mail = self.env['mail.mail']
        antes = Mail.search([], order='id desc', limit=1)
        antes_id = antes.id if antes else 0

        self.Currency.send_email_missing_rate('USD')

        nuevo = Mail.search([('id', '>', antes_id)], order='id desc', limit=1)
        self.assertTrue(nuevo)
        self.assertIn('USD', nuevo.subject)
