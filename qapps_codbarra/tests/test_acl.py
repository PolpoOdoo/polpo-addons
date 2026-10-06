from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

MODELOS = ("qapps.barcode.reader", "qapps.barcode.reader.line")


@tagged("post_install", "-at_install")
class TestAclLectorCodigos(TransactionCase):
    """El lector de codigos de barras queda para usuarios de Inventario: sin grupo
    en el ACL lo podia crear cualquier usuario, incluidos los de portal."""

    def _puede(self, usuario, modelo, modo):
        return self.env["ir.model.access"].with_user(usuario).check(
            modelo, modo, raise_exception=False
        )

    def test_usuario_de_inventario_opera_el_lector(self):
        usuario = new_test_user(self.env, login="lector_stock", groups="stock.group_stock_user")
        for modelo in MODELOS:
            for modo in ("read", "write", "create", "unlink"):
                self.assertTrue(self._puede(usuario, modelo, modo), (modelo, modo))

    def test_usuario_interno_sin_inventario_no_crea(self):
        usuario = new_test_user(self.env, login="lector_interno", groups="base.group_user")
        for modelo in MODELOS:
            self.assertFalse(self._puede(usuario, modelo, "create"), modelo)

    def test_usuario_de_portal_no_accede(self):
        usuario = new_test_user(self.env, login="lector_portal", groups="base.group_portal")
        for modelo in MODELOS:
            self.assertFalse(self._puede(usuario, modelo, "read"), modelo)
