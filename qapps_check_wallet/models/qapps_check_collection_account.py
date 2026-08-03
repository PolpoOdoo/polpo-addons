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
    def _find_mapping(self, company, currency):
        """Mapeo aplicable a una compañía: el propio si existe y, si no, el del
        ancestro más cercano. Las sucursales (branches de Odoo 17) comparten los
        diarios y las cuentas de la compañía madre, así que también comparten
        esta configuración en lugar de tener que duplicarla.

        Devuelve un recordset vacío si no hay ninguno configurado."""
        if not company or not currency:
            return self.browse()
        mappings = self.search(
            [
                ("company_id", "parent_of", company.id),
                ("currency_id", "=", currency.id),
            ]
        )
        if len(mappings) <= 1:
            return mappings
        # Más de un ancestro con mapeo: gana el más específico (el más profundo
        # en el árbol de compañías).
        return mappings.sorted(
            key=lambda m: len(m.company_id.parent_path or ""), reverse=True
        )[:1]

    @api.model
    def _get_for_currency(self, company, currency):
        """Devuelve el registro de mapeo para una compañía y moneda dadas,
        o lanza un error claro si no está configurado."""
        mapping = self._find_mapping(company, currency)
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
