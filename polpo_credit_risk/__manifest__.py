# Copyright 2026 QEI SRL (Polpo)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Control de Crédito Extendido - Polpo",
    "summary": "Control de riesgo crediticio extendido: cheques diferidos en cartera, "
    "crédito adicional temporal y autorización de excepciones con trazabilidad",
    "description": """
Qué hace:
- Extiende res.partner (sobre OCA account_financial_risk / sale_financial_risk)
  con un nuevo rubro de riesgo "Cheques diferidos en cartera"
  (risk_deferred_checks, computado sobre account.move.line en las cuentas de
  cheques en mano de diarios banco sin cuenta bancaria, no conciliados, no
  depositados vía account_check_deposit, con vencimiento futuro — usa el campo
  'vencimiento' de qapps_cheque_info), con su check de inclusión y límite específico.
- Agrega crédito adicional temporal al partner (additional_credit_amount +
  vigencia desde/hasta) y el campo computado effective_credit_limit
  (límite base + adicional vigente). Hace override de _compute_risk_exception
  y _compute_risk_remaining de OCA para evaluar el riesgo contra el límite
  efectivo, y agrega onchange con warnings de coherencia de datos.
- Centraliza la evaluación en res.partner._get_credit_exception_messages(),
  que devuelve TODOS los motivos de bloqueo (deuda vencida, límite de pedidos,
  límite de facturas abiertas, límite de cheques diferidos, riesgo total vs
  límite efectivo), no solo el primero, forzando recompute de los campos de
  riesgo stored para evitar valores desactualizados.
- Extiende sale.order (action_confirm) y account.move (action_post) para que,
  ante una excepción de riesgo, se abra el wizard propio
  polpo.credit.override.wiz en lugar del wizard OCA. Solo usuarios del grupo
  "Autorizador de crédito" (group_credit_authorizer) pueden autorizar; la
  autorización queda registrada en el documento (usuario, fecha, motivo,
  flag "Operado bajo excepción" + ribbon) y en el chatter, y luego continúa
  la operación original con bypass_risk. El wizard tiene allowlist de
  modelo/método permitidos como defensa contra ejecución arbitraria vía RPC.
- Muestra banners de advertencia informativos (credit_warning_msg) en
  cotizaciones draft/sent y facturas de cliente en borrador.
- Rediseña la pestaña "Riesgo financiero" del partner como matriz de rubros
  (monto actual con drill-down, check de inclusión y límite específico por
  fila) reemplazando el layout de dos columnas de OCA.

Para qué sirve:
Control de riesgo crediticio de clientes en la venta y la facturación:
bloquear (con posibilidad de autorización supervisada y auditable) la
confirmación de pedidos y el posteo de facturas cuando el cliente tiene
deuda vencida, excede su límite de crédito (considerando cheques diferidos
aún no depositados como riesgo) o supera límites específicos por rubro.
El crédito adicional temporal permite otorgar ampliaciones de límite
acotadas en el tiempo sin modificar el límite base.

Alcance:
Control de riesgo crediticio para operaciones de venta y facturación.
Convive con las customizaciones de la base donde se instale.

Configuración:
- Depende de OCA sale_financial_risk, account_financial_risk y
  account_check_deposit, más qapps_cheque_info (campo vencimiento en apuntes)
- Crea el grupo de seguridad "Autorizador de crédito"
  (polpo_credit_risk.group_credit_authorizer), que implica el grupo de
  usuario de riesgo financiero OCA. Se asigna explícitamente por usuario;
  intencionalmente NO está implicado desde base.group_erp_manager.
- Los cheques diferidos se detectan en diarios tipo banco sin cuenta
  bancaria, en la cuenta de pagos del método de pago entrante "manual".
""",
    "sequence": 150,
    "version": "17.0.1.5.4",
    "category": "Accounting",
    "license": 'AGPL-3',
    "author": "Polpo ERP",
    "website": "https://polpo.uy",
    "support": "info@polpo.uy",
    "depends": [
        "sale_financial_risk",
        "account_financial_risk",
        "account_check_deposit",
        "qapps_cheque_info",
        ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "wizards/credit_override_wizard_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
}
