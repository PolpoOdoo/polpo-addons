# -*- coding: utf-8 -*-
"""La pestaña Retenciones / CCE tiene que verse en las notas de credito de
cliente: ahi se carga el % de retencion en garantia de una NC sin factura
de origen."""
from lxml import etree

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestPaginaRetencionesEnNc(TransactionCase):

    def _invisible_de_la_pagina(self):
        arch = etree.fromstring(
            self.env["account.move"].get_view(
                view_id=self.env.ref("account.view_move_form").id, view_type="form"
            )["arch"]
        )
        paginas = arch.xpath("//page[@name='qapps_retenciones_cce_page']")
        self.assertTrue(paginas, "la pagina Retenciones / CCE no esta en el form")
        return paginas[0].get("invisible") or "False"

    def _esta_oculta_para(self, expresion, move_type):
        """Evalua el modificador del arch, que es lo que decide la visibilidad
        real: assertar que el nodo existe no prueba nada, el nodo esta siempre."""
        return bool(safe_eval(expresion, {"move_type": move_type}))

    def test_la_pestana_se_muestra_en_notas_de_credito_de_cliente(self):
        expresion = self._invisible_de_la_pagina()
        self.assertFalse(self._esta_oculta_para(expresion, "out_refund"))

    def test_la_pestana_sigue_visible_en_las_facturas(self):
        expresion = self._invisible_de_la_pagina()
        for move_type in ("out_invoice", "in_invoice"):
            self.assertFalse(self._esta_oculta_para(expresion, move_type))

    def test_la_pestana_no_se_muestra_en_asientos_ni_en_nc_de_proveedor(self):
        expresion = self._invisible_de_la_pagina()
        for move_type in ("entry", "in_refund"):
            self.assertTrue(self._esta_oculta_para(expresion, move_type))
