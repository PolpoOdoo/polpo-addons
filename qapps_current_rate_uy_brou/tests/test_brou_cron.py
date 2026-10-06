from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBrouCron(TransactionCase):
    """El booleano de Ajustes prende y apaga, al guardar, un cron que el modulo trae definido."""

    def _cron(self):
        return self.env.ref("qapps_current_rate_uy_brou.ir_cron_fetch_brou_rates")

    def _ajustes(self, valor):
        form = Form(self.env["res.config.settings"])
        form.brou_currency_update = valor
        return form.save()

    def test_cron_definido_y_apagado(self):
        cron = self._cron()
        self.assertFalse(cron.active)
        self.assertEqual(cron.code.strip(), "model.fetch_brou_rates()")
        self.assertEqual(cron.model_id.model, "res.currency.rate")

    def test_guardar_ajustes_prende_y_apaga_el_cron(self):
        self._ajustes(True).execute()
        self.assertTrue(self._cron().active)
        self._ajustes(False).execute()
        self.assertFalse(self._cron().active)

    def test_tildar_sin_guardar_no_prende_el_cron(self):
        self._ajustes(True)
        self.assertFalse(self._cron().active)
