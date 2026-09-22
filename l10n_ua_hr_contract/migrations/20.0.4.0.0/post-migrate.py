"""Drop what hr.work.schedule left behind (#213, phase 2).

Odoo removes the ir.model / ir.model.fields / ir.ui.view / ir.actions /
ir.rule / ir.model.access records of a model that a module no longer declares,
but it never drops the SQL tables of that model, nor the columns of the fields
that went away. This does, once the guard in pre-migrate has confirmed every
version carries a working hours calendar.

The 20.0.3.0.0 backups (`hr_work_schedule_backup_19_3_0`,
`hr_work_schedule_line_backup_19_3_0`, `hr_version_calendar_backup_19_3_0`)
are deliberately kept: they are the only remaining copy of the mapping once
the live tables are gone.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

DROPPED_COLUMNS = (
    ('hr_version', 'work_schedule_ua_id'),
    ('hr_version', 'working_hours_week'),
)

DROPPED_TABLES = ('hr_work_schedule_line', 'hr_work_schedule')


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)", (table, column))
    return cr.fetchone()[0]


# Records the standard cleanup cannot reach: an ir.rule has an
# ondelete=cascade foreign key to ir.model, so deleting the model of
# hr.work.schedule takes the rule out behind the ORM's back — by the time Odoo
# gets to the obsolete-data pass, the record is gone and only its ir.model.data
# row is left, pointing at nothing. Removing them here, while the record is
# still there, keeps the database clean.
CASCADED_XML_IDS = ('hr_work_schedule_company_rule',)


def _drop_cascaded_records(cr, env):
    for name in CASCADED_XML_IDS:
        record = env.ref('l10n_ua_hr_contract.%s' % name,
                         raise_if_not_found=False)
        if record:
            record.unlink()
            _logger.info(
                "l10n_ua_hr_contract 20.0.4.0.0: removed %s", name)
    cr.execute(
        "DELETE FROM ir_model_data WHERE module = 'l10n_ua_hr_contract' "
        "AND name IN %s", (CASCADED_XML_IDS,))


def _drop_dangling_xml_ids(cr):
    """Remove XML ids of the feature whose record is already gone.

    Only rows whose target is really missing are deleted: the rest are the
    module's own bookkeeping, and removing them would stop Odoo from cleaning
    up the records they still stand for.
    """
    cr.execute("""
        SELECT id, model, res_id FROM ir_model_data
        WHERE module = 'l10n_ua_hr_contract'
          AND name LIKE %s
    """, ('%work_schedule%',))
    rows = cr.fetchall()

    dangling = []
    for data_id, model, res_id in rows:
        table = model.replace('.', '_')
        cr.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables "
            "WHERE table_name = %s)", (table,))
        if not cr.fetchone()[0]:
            dangling.append(data_id)
            continue
        cr.execute(
            'SELECT EXISTS (SELECT FROM "%s" WHERE id = %%s)' % table,
            (res_id,))
        if not cr.fetchone()[0]:
            dangling.append(data_id)

    if dangling:
        cr.execute("DELETE FROM ir_model_data WHERE id IN %s",
                   (tuple(dangling),))
        _logger.info(
            "l10n_ua_hr_contract 20.0.4.0.0: removed %s dangling XML ids of "
            "the deleted work schedules", len(dangling))


def migrate(cr, version):
    if not version:
        return

    for table, column in DROPPED_COLUMNS:
        if not _column_exists(cr, table, column):
            continue
        cr.execute('ALTER TABLE "%s" DROP COLUMN "%s"' % (table, column))
        _logger.info(
            "l10n_ua_hr_contract 20.0.4.0.0: dropped column %s.%s",
            table, column)

    for table in DROPPED_TABLES:
        cr.execute('DROP TABLE IF EXISTS "%s" CASCADE' % table)
    _logger.info(
        "l10n_ua_hr_contract 20.0.4.0.0: dropped tables %s; the 20.0.3.0.0 "
        "backup tables are kept as the record of the old mapping",
        ', '.join(DROPPED_TABLES))

    env = api.Environment(cr, SUPERUSER_ID, {})
    _drop_cascaded_records(cr, env)
    _drop_dangling_xml_ids(cr)
