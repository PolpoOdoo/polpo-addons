# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.qapps_website_autocomplete_uy.controllers.main import AutoCompleteControllerUY


@tagged('post_install', '-at_install')
class TestAutocompleteUY(TransactionCase):
    """Sin país/idioma, la búsqueda de Google debe sesgarse a Uruguay (es-419)."""

    def _run_search(self, **kwargs):
        controller = AutoCompleteControllerUY()
        captured = {}
        fake_resp = MagicMock()
        fake_resp.json.return_value = {'predictions': []}

        def fake_get(url, params=None, timeout=None):
            captured['params'] = params
            return fake_resp

        target = 'odoo.addons.website_sale_autocomplete.controllers.main.requests.get'
        with patch(target, side_effect=fake_get):
            controller._perform_place_search(
                'Av 18 de Julio 1234', api_key='DUMMY-KEY', **kwargs
            )
        return captured.get('params', {})

    def test_defaults_to_uruguay_and_es419(self):
        params = self._run_search()
        self.assertEqual(params.get('components'), 'country:UY')
        self.assertEqual(params.get('language'), 'es-419')

    def test_explicit_values_are_respected(self):
        params = self._run_search(country_code='AR', language_code='pt-BR')
        self.assertEqual(params.get('components'), 'country:AR')
        self.assertEqual(params.get('language'), 'pt-BR')
