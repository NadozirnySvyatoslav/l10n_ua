import logging

_logger = logging.getLogger(__name__)

BACKUP = 'hr_version_staffing_backup_19_7_0'


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)", (table, column))
    return cr.fetchone()[0]


def migrate(cr, version):
    """Snapshot the manual staffing pointer before it becomes a derived field.

    From 19.0.7.0.0 `hr.version.staffing_line_id` is computed from
    department + job + date instead of being picked by hand, and its column
    goes away. This table is the only surviving record of what each version
    used to point at, so post-migrate reads the mapping from here rather than
    from a column the upgrade is about to drop — and a rollback still has
    something to restore from.

    `job_title` and `is_custom_job_title` travel along: post-migrate fills in
    the native position fields, and core recomputes the job title from the
    position, which would silently discard a title that was typed by hand.
    """
    if not version:
        return

    if not _column_exists(cr, 'hr_version', 'staffing_line_id'):
        _logger.info(
            "l10n_ua_hr_contract 19.0.7.0.0: hr_version.staffing_line_id "
            "absent, nothing to snapshot")
        return

    cr.execute('DROP TABLE IF EXISTS %s' % BACKUP)
    cr.execute("""
        CREATE TABLE %s AS
        SELECT id AS version_id,
               staffing_line_id,
               department_id,
               job_id,
               job_title,
               is_custom_job_title
        FROM hr_version
    """ % BACKUP)

    cr.execute(
        'SELECT COUNT(*), COUNT(staffing_line_id) FROM %s' % BACKUP)
    total, with_line = cr.fetchone()
    _logger.info(
        "l10n_ua_hr_contract 19.0.7.0.0: snapshotted %s versions into %s, "
        "%s of them carrying a manual staffing line",
        total, BACKUP, with_line)
