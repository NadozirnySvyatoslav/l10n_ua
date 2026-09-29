"""Hand hr.order's time-off fields over to l10n_ua_hr_holidays.

``leave_id``, ``holiday_status_id``, ``leave_count`` and ``can_create_leave``
used to be declared here, which forced this module to depend on
``hr_holidays`` while the reverse side of the link (``hr.leave.order_id``)
lives in ``l10n_ua_hr_holidays``. They are now declared there, on both sides.

No value moves: ``hr_order.leave_id`` and ``hr_order.holiday_status_id`` stay
in the same columns of the same table. What changes is who owns them, and
that ownership is recorded in ``ir_model_data``. Odoo's end-of-load cleanup
deletes the ``ir.model.fields`` rows whose external id belongs to an upgraded
module and was not re-created during that load — and deleting such a row
drops its column. Reassigning the external ids before the models are loaded
is what keeps the existing order-to-leave links intact.

Nothing is reassigned when l10n_ua_hr_holidays is not installed: the fields
are then genuinely gone, and their columns should go with them.
"""

MOVED_FIELDS = (
    'field_hr_order__leave_id',
    'field_hr_order__holiday_status_id',
    'field_hr_order__leave_count',
    'field_hr_order__can_create_leave',
)

OLD_MODULE = 'l10n_ua_hr_documents'
NEW_MODULE = 'l10n_ua_hr_holidays'


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT 1 FROM ir_module_module WHERE name = %s AND state IN %s",
        (NEW_MODULE, ('installed', 'to upgrade', 'to install')),
    )
    if not cr.fetchone():
        return

    # Idempotent: on a database where l10n_ua_hr_holidays already reflected
    # the fields under its own name, the old external id is a leftover and is
    # dropped instead of renamed — (module, name) is unique.
    cr.execute(
        """
        DELETE FROM ir_model_data old
              WHERE old.module = %s
                AND old.name IN %s
                AND EXISTS (SELECT 1 FROM ir_model_data new
                             WHERE new.module = %s
                               AND new.name = old.name)
        """,
        (OLD_MODULE, MOVED_FIELDS, NEW_MODULE),
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET module = %s
         WHERE module = %s
           AND name IN %s
        """,
        (NEW_MODULE, OLD_MODULE, MOVED_FIELDS),
    )
