import logging
import requests
from bs4 import BeautifulSoup
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

class ResCurrencyRate(models.Model):
    _inherit = "res.currency.rate"

    @api.model
    def fetch_brou_rates(self):
        url = "https://www.brou.com.uy/c/portal/render_portlet?p_l_id=20593&p_p_id=cotizacionfull_WAR_broutmfportlet_INSTANCE_otHfewh1klyS&p_p_lifecycle=0&p_t_lifecycle=0&p_p_state=normal&p_p_mode=view&p_p_col_id=column-1&p_p_col_pos=0&p_p_col_count=2&p_p_isolated=1&currentURL=%2Fcotizaciones"

        try:
            req = requests.get(url, timeout=30)
            soup = BeautifulSoup(req.text, "html.parser")
            table = soup.find("table")

            if not table:
                return

            fecha_carga = fields.Date.today()
            empresas = self.env["res.company"].search([("active", "=", True)])
            currency_dol = self.env["res.currency"].search([("name", "=", "DOL")], limit=1)
            currency_doc = self.env["res.currency"].search([("name", "=", "DOC")], limit=1)

            # Busco SOLO la fila de "Dólar"
            dolar_row = next((row for row in table.find_all("tr")[1:]
                              if row.find("p", class_="moneda") and row.find("p", class_="moneda").text.strip() == "Dólar"), None)

            if dolar_row:
                cols = dolar_row.find_all("td")
                compra = cols[2].find("p", class_="valor").text.strip().replace(",", ".") if cols[2].find("p", class_="valor") else "0.0"
                venta = cols[4].find("p", class_="valor").text.strip().replace(",", ".") if cols[4].find("p", class_="valor") else "0.0"

                for company in empresas:
                    # Guardar la tasa de venta en DOL
                    if currency_dol:
                        existing_dol_rate = self.search([
                            ("currency_id", "=", currency_dol.id),
                            ("name", "=", fecha_carga),
                            ("company_id", "=", company.id)
                        ], limit=1)

                        if not existing_dol_rate and float(venta) > 0:
                            self.create({
                                "company_id": company.id,
                                "currency_id": currency_dol.id,
                                "name": fecha_carga,
                                "rate": 1 / float(venta)
                            })

                    # Guardar la tasa de compra en DOC
                    if currency_doc:
                        existing_doc_rate = self.search([
                            ("currency_id", "=", currency_doc.id),
                            ("name", "=", fecha_carga),
                            ("company_id", "=", company.id)
                        ], limit=1)

                        if not existing_doc_rate and float(compra) > 0:
                            self.create({
                                "company_id": company.id,
                                "currency_id": currency_doc.id,
                                "name": fecha_carga,
                                "rate": 1 / float(compra)
                            })

        except Exception as e:
            _logger.warning("Error en fetch_brou_rates(): %s", str(e))
