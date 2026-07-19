import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """CR-02: revierte la herencia stale base.group_erp_manager ->
    polpo_credit_risk.group_credit_authorizer en bases actualizadas desde la
    version con implied.

    El fix removio el implied del XML (security.xml), pero un ``-u`` no borra
    ni la fila de implicacion existente (res_groups_implied_rel) ni la
    membresia del grupo autorizador que quedo materializada en cada usuario de
    Ajustes (res_groups_users_rel). Resultado: todo usuario erp_manager seguia
    siendo autorizador de credito. Esta migracion:
      1) elimina la implicacion erp_manager -> autorizador; y
      2) revoca el grupo autorizador a los usuarios que lo tienen SOLO por ser
         erp_manager (herencia vieja), para que se asigne explicitamente.

    Los autorizadores reales que ademas sean erp_manager deben re-asignarse el
    grupo "Autorizador de credito" manualmente; se loguean los uid afectados.
    """
    cr.execute(
        """
        SELECT d1.res_id, d2.res_id
        FROM ir_model_data d1, ir_model_data d2
        WHERE d1.module = 'base' AND d1.name = 'group_erp_manager'
          AND d2.module = 'polpo_credit_risk'
          AND d2.name = 'group_credit_authorizer'
        """
    )
    row = cr.fetchone()
    if not row:
        return
    erp_manager_id, authorizer_id = row

    # 1) quitar la implicacion erp_manager -> autorizador
    cr.execute(
        "DELETE FROM res_groups_implied_rel WHERE gid = %s AND hid = %s",
        (erp_manager_id, authorizer_id),
    )
    implied_removed = cr.rowcount

    # 2) revocar el autorizador a quienes lo heredaron por ser erp_manager
    cr.execute(
        """
        SELECT uid FROM res_groups_users_rel
        WHERE gid = %s
          AND uid IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
        """,
        (authorizer_id, erp_manager_id),
    )
    affected = [r[0] for r in cr.fetchall()]
    if affected:
        cr.execute(
            "DELETE FROM res_groups_users_rel WHERE gid = %s AND uid = ANY(%s)",
            (authorizer_id, affected),
        )
    _logger.info(
        "polpo_credit_risk CR-02: implied removido (%s fila/s); autorizador de "
        "credito revocado a %s usuario(s) erp_manager: %s. Re-asignar explicito "
        "a los autorizadores reales.",
        implied_removed,
        len(affected),
        affected,
    )
