# -*- coding: utf-8 -*-
"""Tests para qapps_current_rate_uy_brou.

Cubren la obtención de cotización del BROU mediante scraping HTML:
parseo de la tabla, cálculo de la tasa (1/venta -> DOL, 1/compra -> DOC),
creación de res.currency.rate, idempotencia y manejo de errores.

CRÍTICO: nunca se llama al BROU real. Toda la capa HTTP (requests.get)
está mockeada con unittest.mock.patch. El HTML que devuelve el mock es
un stub controlado, no una respuesta real.
"""
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase, tagged
from odoo import fields

# Ruta del símbolo 'requests' tal como lo importa el modelo bajo test.
RUTA_REQUESTS = "odoo.addons.qapps_current_rate_uy_brou.models.brou_scraper.requests"


def _html_brou(compra="42,50", venta="44,80", incluir_dolar=True):
    """Construye un HTML que imita la estructura que parsea el scraper.

    El parser busca:
      - la primera <table>
      - filas (tr) salteando la primera (cabecera)
      - en cada fila un <p class="moneda"> cuyo texto == "Dólar"
      - dentro de esa fila: cols[2] -> compra, cols[4] -> venta,
        cada uno con un <p class="valor">.
    Por eso la fila del dólar tiene al menos 5 <td>.
    """
    fila_dolar = ""
    if incluir_dolar:
        fila_dolar = (
            "<tr>"
            "<td><p class='moneda'>Dólar</p></td>"          # col 0: nombre
            "<td><p class='valor'>arbitraje</p></td>"            # col 1: ruido
            "<td><p class='valor'>{compra}</p></td>"             # col 2: COMPRA
            "<td><p class='valor'>ignorado</p></td>"             # col 3: ruido
            "<td><p class='valor'>{venta}</p></td>"              # col 4: VENTA
            "</tr>"
        ).format(compra=compra, venta=venta)

    return (
        "<html><body>"
        "<table>"
        "<tr><th>Moneda</th><th>x</th><th>Compra</th><th>y</th><th>Venta</th></tr>"
        "<tr>"
        "<td><p class='moneda'>Euro</p></td>"
        "<td><p class='valor'>e1</p></td>"
        "<td><p class='valor'>47,00</p></td>"
        "<td><p class='valor'>e3</p></td>"
        "<td><p class='valor'>49,00</p></td>"
        "</tr>"
        "{fila_dolar}"
        "</table>"
        "</body></html>"
    ).format(fila_dolar=fila_dolar)


@tagged("post_install", "-at_install")
class TestBrouScraper(TransactionCase):

    def setUp(self):
        super().setUp()
        self.ResRate = self.env["res.currency.rate"]
        # Monedas descartables y propias del test (no se depende de las del entorno).
        self.moneda_dol = self.env["res.currency"].create({
            "name": "DOL",
            "symbol": "U$S-V",
            "active": True,
        })
        self.moneda_doc = self.env["res.currency"].create({
            "name": "DOC",
            "symbol": "U$S-C",
            "active": True,
        })
        # Empresa de prueba propia (no se copia res.company del entorno;
        # se usa la empresa principal activa que siempre existe).
        self.empresa = self.env.company

    def _mock_response(self, texto_html):
        """Crea un objeto que simula la respuesta de requests.get."""
        resp = MagicMock()
        resp.text = texto_html
        return resp

    def _tasas_de_hoy(self, moneda, company=None):
        """Tasas de hoy para `moneda`, acotadas a una compañía.

        El scraper es multi-company por diseño: itera sobre TODAS las
        compañías activas (`fetch_brou_rates` -> `for company in empresas`)
        y crea una tasa por compañía/moneda/fecha. La base `qa_core` puede
        tener varias compañías, por lo que sin acotar habría N tasas y
        `.rate`/`len()==1` fallarían. Se acota a `self.empresa`
        (= env.company) para validar una sola tasa de forma determinista.
        """
        hoy = fields.Date.today()
        return self.ResRate.search([
            ("currency_id", "=", moneda.id),
            ("name", "=", hoy),
            ("company_id", "=", (company or self.empresa).id),
        ])

    # ---------------------------------------------------------------
    # Parseo + cálculo + creación
    # ---------------------------------------------------------------
    def test_parseo_crea_tasas_dol_y_doc(self):
        """Con HTML válido crea DOL (1/venta) y DOC (1/compra) para la empresa."""
        html = _html_brou(compra="40,00", venta="50,00")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        # No se golpeó al BROU real: el mock fue el único punto de red.
        self.assertTrue(mock_req.get.called, "Debió llamar a requests.get (mockeado)")

        tasas_dol = self._tasas_de_hoy(self.moneda_dol)
        tasas_doc = self._tasas_de_hoy(self.moneda_doc)
        self.assertEqual(len(tasas_dol), 1, "Debe crear exactamente una tasa DOL hoy")
        self.assertEqual(len(tasas_doc), 1, "Debe crear exactamente una tasa DOC hoy")

        # DOL = 1/venta = 1/50 = 0.02 ; DOC = 1/compra = 1/40 = 0.025
        self.assertAlmostEqual(tasas_dol.rate, 1.0 / 50.0, places=6)
        self.assertAlmostEqual(tasas_doc.rate, 1.0 / 40.0, places=6)

    def test_coma_decimal_se_convierte_a_punto(self):
        """El valor del BROU viene con coma decimal y debe parsearse correctamente."""
        html = _html_brou(compra="42,50", venta="44,80")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        self.assertAlmostEqual(self._tasas_de_hoy(self.moneda_dol).rate, 1.0 / 44.80, places=6)
        self.assertAlmostEqual(self._tasas_de_hoy(self.moneda_doc).rate, 1.0 / 42.50, places=6)

    def test_tasa_se_crea_para_empresa_activa(self):
        """La tasa creada queda asociada a una empresa activa."""
        html = _html_brou()
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        tasa = self._tasas_de_hoy(self.moneda_dol)
        self.assertTrue(tasa.company_id, "La tasa debe tener company_id")
        self.assertTrue(tasa.company_id.active, "La empresa de la tasa debe estar activa")

    # ---------------------------------------------------------------
    # Idempotencia
    # ---------------------------------------------------------------
    def test_idempotente_no_duplica_si_ya_existe(self):
        """Dos corridas el mismo día no duplican la tasa por empresa/moneda/fecha."""
        html = _html_brou(compra="40,00", venta="50,00")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()
            self.ResRate.fetch_brou_rates()  # segunda corrida

        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 1,
                         "No debe duplicar DOL en la misma fecha")
        self.assertEqual(len(self._tasas_de_hoy(self.moneda_doc)), 1,
                         "No debe duplicar DOC en la misma fecha")

    def test_no_pisa_tasa_preexistente(self):
        """Si ya hay una tasa para hoy, el scraper no la sobreescribe."""
        hoy = fields.Date.today()
        self.ResRate.create({
            "company_id": self.empresa.id,
            "currency_id": self.moneda_dol.id,
            "name": hoy,
            "rate": 0.111,
        })
        html = _html_brou(compra="40,00", venta="50,00")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        tasa_dol = self.ResRate.search([
            ("currency_id", "=", self.moneda_dol.id),
            ("name", "=", hoy),
            ("company_id", "=", self.empresa.id),
        ])
        self.assertEqual(len(tasa_dol), 1)
        self.assertAlmostEqual(tasa_dol.rate, 0.111, places=6,
                               msg="No debe pisar la tasa DOL preexistente")

    # ---------------------------------------------------------------
    # Manejo de error / casos límite
    # ---------------------------------------------------------------
    def test_sin_tabla_no_crea_nada(self):
        """Respuesta sin <table>: retorna sin crear tasas (no rompe)."""
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response("<html><body>nada</body></html>")
            self.ResRate.fetch_brou_rates()

        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 0)
        self.assertEqual(len(self._tasas_de_hoy(self.moneda_doc)), 0)

    def test_sin_fila_dolar_no_crea_nada(self):
        """Hay tabla pero no fila 'Dólar': no crea tasas."""
        html = _html_brou(incluir_dolar=False)
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 0)
        self.assertEqual(len(self._tasas_de_hoy(self.moneda_doc)), 0)

    def test_excepcion_de_red_se_traga_y_no_rompe(self):
        """Un error en requests.get se captura y logea, sin propagar excepción."""
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.side_effect = Exception("fallo de red simulado")
            # No debe levantar excepción.
            self.ResRate.fetch_brou_rates()

        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 0)
        self.assertEqual(len(self._tasas_de_hoy(self.moneda_doc)), 0)

    def test_venta_cero_no_persiste_tasa(self):
        """venta=0 NO produce tasa DOL, pero compra>0 SÍ produce tasa DOC.

        Comportamiento correcto tras el fix de causa-raíz en brou_scraper.py
        (guardas ``float(venta) > 0`` / ``float(compra) > 0`` en :48 y :64):
        cuando venta/compra no es > 0 el scraper SALTEA el create de esa tasa
        en vez de escribir ``rate=0.0`` (que violaba CHECK(rate>0) y, vía el
        ``except`` amplio de ``fetch_brou_rates``, abortaba TODA la transacción
        del lote). Con el fix, venta=0 deja sin crear la tasa DOL, pero la tasa
        DOC (compra=40 -> 1/40) persiste normalmente porque cada create es
        independiente y ninguno aborta la transacción.
        """
        html = _html_brou(compra="40,00", venta="0")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        # venta=0 -> la guarda saltea el create -> no hay tasa DOL.
        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 0,
                         "venta=0 no debe crear tasa DOL (guarda venta>0)")
        # compra=40>0 -> DOC se crea con rate=1/40, sin verse afectada por venta=0.
        tasas_doc = self._tasas_de_hoy(self.moneda_doc)
        self.assertEqual(len(tasas_doc), 1,
                         "compra>0 debe persistir la tasa DOC (transacción no aborta)")
        self.assertAlmostEqual(tasas_doc.rate, 1.0 / 40.0, places=6)

    def test_sin_moneda_doc_solo_crea_dol(self):
        """Si no existe la moneda DOC, solo se crea la tasa DOL."""
        # Renombro DOC para que la búsqueda por name='DOC' no la encuentre.
        self.moneda_doc.name = "ZZZ"
        html = _html_brou(compra="40,00", venta="50,00")
        with patch(RUTA_REQUESTS) as mock_req:
            mock_req.get.return_value = self._mock_response(html)
            self.ResRate.fetch_brou_rates()

        self.assertEqual(len(self._tasas_de_hoy(self.moneda_dol)), 1,
                         "DOL debe crearse igual")
        # No hay moneda DOC -> no se crea su tasa.
        tasas_zzz = self.ResRate.search([
            ("currency_id", "=", self.moneda_doc.id),
            ("name", "=", fields.Date.today()),
        ])
        self.assertEqual(len(tasas_zzz), 0, "Sin moneda DOC no debe crear su tasa")
