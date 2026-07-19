from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QappsCheckCollectionAccount(models.Model):
    """Mapeo por moneda de las cuentas puente de cheques al cobro y de cheques
    rechazados. Evita hardcodear códigos de cuenta: el administrador configura,
    por compañía y moneda, qué cuenta usar como puente y cuál para rechazos."""

    _name = "qapps.check.collection.account"
    _description = "Cuentas de cheques al cobro / rechazados por moneda"
    _check_company_auto = True
    _order = "company_id, currency_id"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Moneda",
        required=True,
        help="Moneda a la que aplican estas cuentas: hay un mapeo por moneda y compañía.",
    )
    collection_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta cheques al cobro",
        required=True,
        check_company=True,
        help="Cuenta puente donde quedan los cheques enviados al banco al cobro, "
        "hasta su acreditación o rechazo.",
    )
    rejected_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Cuenta cheques rechazados",
        required=True,
        check_company=True,
        help="Cuenta donde se contabilizan los cheques al cobro que el banco rechaza.",
    )

    _sql_constraints = [
        (
            "company_currency_unique",
            "unique(company_id, currency_id)",
            "Ya existe una configuración de cuentas para esta moneda en esta compañía.",
        )
    ]

    @api.model
    def _get_for_currency(self, company, currency):
        """Devuelve el registro de mapeo para una compañía y moneda dadas,
        o lanza un error claro si no está configurado."""
        mapping = self.search(
            [
                ("company_id", "=", company.id),
                ("currency_id", "=", currency.id),
            ],
            limit=1,
        )
        if not mapping:
            raise UserError(
                _(
                    "No hay cuentas de cheques al cobro configuradas para la moneda "
                    "'%(currency)s' en la compañía '%(company)s'.\n\n"
                    "Configúrelas en Contabilidad > Configuración > Cheques al cobro: cuentas.",
                    currency=currency.display_name,
                    company=company.display_name,
                )
            )
        return mapping
