import logging

_logger = logging.getLogger(__name__)

BACKUP_TABLES = (
    ('hr_work_schedule', 'hr_work_schedule_backup_19_3_0'),
    ('hr_work_schedule_line', 'hr_work_schedule_line_backup_19_3_0'),
)


def _table_exists(cr, table):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables "
        "WHERE table_name = %s)", (table,))
    return cr.fetchone()[0]


def migrate(cr, version):
    """Back up everything 20.0.3.0.0 is about to switch away from.

    The upgrade itself is reversible field by field: the UA schedule tables are
    copied verbatim, and the current version→calendar mapping is snapshotted so
    a rollback can restore each version's calendar exactly as it was.
    """
    if not version:
        return

    if not _table_exists(cr, 'hr_work_schedule'):
        _logger.info(
            "l10n_ua_hr_contract 20.0.3.0.0: hr_work_schedule table absent, "
            "nothing to back up (clean install)")
        return

    for source, backup in BACKUP_TABLES:
        if not _table_exists(cr, source):
            continue
        cr.execute('DROP TABLE IF EXISTS %s' % backup)
        cr.execute('CREATE TABLE %s AS SELECT * FROM %s' % (backup, source))
        cr.execute('SELECT COUNT(*) FROM %s' % backup)
        _logger.info(
            "l10n_ua_hr_contract 20.0.3.0.0: backed up %s rows of %s into %s",
            cr.fetchone()[0], source, backup)

    cr.execute('DROP TABLE IF EXISTS hr_version_calendar_backup_19_3_0')
    cr.execute("""
        CREATE TABLE hr_version_calendar_backup_19_3_0 AS
        SELECT id AS version_id,
               work_schedule_ua_id,
               working_hours_week,
               resource_calendar_id
        FROM hr_version
    """)
    cr.execute('SELECT COUNT(*) FROM hr_version_calendar_backup_19_3_0')
    _logger.info(
        "l10n_ua_hr_contract 20.0.3.0.0: snapshotted calendar mapping for "
        "%s versions", cr.fetchone()[0])
