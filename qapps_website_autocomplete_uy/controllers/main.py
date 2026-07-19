from odoo.addons.website_sale_autocomplete.controllers.main import (
    AutoCompleteController,
)

# Valores por defecto cuando la búsqueda no especifica país/idioma.
QAPPS_DEFAULT_COUNTRY_CODE = "UY"
QAPPS_DEFAULT_LANGUAGE_CODE = "es-419"


class AutoCompleteControllerUY(AutoCompleteController):
    def _perform_place_search(
        self,
        partial_address,
        api_key=None,
        session_id=None,
        language_code=None,
        country_code=None,
    ):
        """Override: sesga el autocompletado hacia Uruguay / español (es-419)
        cuando no se pasa país ni idioma.

        Reintroduce como override la customización de core perdida en el update
        de upstream (commit 8766ecd10). Fija los valores por defecto ANTES de
        llamar al core, con lo que se replica exactamente el comportamiento
        original (solo aplica el default cuando el valor viene vacío).
        """
        if not country_code:
            country_code = QAPPS_DEFAULT_COUNTRY_CODE
        if not language_code:
            language_code = QAPPS_DEFAULT_LANGUAGE_CODE
        return super()._perform_place_search(
            partial_address,
            api_key=api_key,
            session_id=session_id,
            language_code=language_code,
            country_code=country_code,
        )
