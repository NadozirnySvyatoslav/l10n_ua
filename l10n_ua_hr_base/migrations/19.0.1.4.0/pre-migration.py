"""Report, before anything commits, what the new staffing rules will change.

Two scans, both read-only. One is about a guarantee that may fail to be
created; the other is about money that may quietly stop being paid.

From 19.0.1.4.0 a position keeps a history of approved staffing lines: each runs
until the next one starts, and the line an employee resolves to is chosen by
date. That leaves exactly one thing the ordering cannot survive — two approved
lines of the same position starting on the same day. They come back from the
database in whatever order the query plan produces, so the same data could yield
a different salary tomorrow, and where a version carries no wage of its own that
difference is a payslip.

A unique index refuses them from now on. It is created while the module loads,
and if the data does not allow it Odoo does not stop the upgrade: it logs the
failure to the schema logger and carries on. The database would then be left
without the guarantee and nobody the wiser — hence this report, before the
attempt, with the ids needed to sort things out.

Nothing is modified. Which of two lines starting the same day holds the truth is
a statement about the staffing table, and about wages already paid, that a
migration has no standing to make.
"""

import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s", (table, column))
    return bool(cr.fetchone())


def _report_discontinued_positions(cr):
    """Positions that will stop resolving because `date_to` changed meaning.

    `date_to` used to be "Effective Until" — the end of this line's own period,
    filled in by hand whenever an officer closed a line. From 19.0.1.4.0 it
    means "Position Discontinued": the resolution stops at a line whose
    `date_to` has passed and deliberately does not fall through to an older
    one, because a position that was abolished does not come back.

    On a database where "Effective Until" was filled in as a matter of habit,
    that turns into a hole. Where the hole is at the end — the newest approved
    line of a position carries a past date — the position resolves to nothing
    at all, and for an employee whose version carries no wage the next payslip
    is a silent zero. Where it is in the middle, only recalculations of the
    months inside it are affected.

    Nothing is changed here. Which lines were meant as "the position ended" and
    which as "we closed this line and opened the next" is a statement about
    orders that were signed, and a migration cannot read them. But the list has
    to exist before the upgrade commits, because afterwards the first sign of
    it is a payslip.
    """
    cr.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (company_id, department_id, job_id)
                   id, company_id, department_id, job_id, date_from, date_to
              FROM hr_staffing_table
             WHERE state = 'approved'
             ORDER BY company_id, department_id, job_id, date_from DESC, id DESC
        )
        SELECT l.id, l.company_id, l.department_id, l.job_id, l.date_to,
               d.name->>'en_US', j.name->>'en_US'
          FROM latest l
          LEFT JOIN hr_department d ON d.id = l.department_id
          LEFT JOIN hr_job j ON j.id = l.job_id
         WHERE l.date_to IS NOT NULL
           AND l.date_to < CURRENT_DATE
         ORDER BY 6, 7
    """)
    dead = cr.fetchall()

    cr.execute("""
        SELECT s.id, s.date_to, min(n.date_from),
               d.name->>'en_US', j.name->>'en_US'
          FROM hr_staffing_table s
          JOIN hr_staffing_table n
            ON n.state = 'approved'
           AND n.company_id = s.company_id
           AND n.department_id IS NOT DISTINCT FROM s.department_id
           AND n.job_id IS NOT DISTINCT FROM s.job_id
           AND n.date_from > s.date_from
          LEFT JOIN hr_department d ON d.id = s.department_id
          LEFT JOIN hr_job j ON j.id = s.job_id
         WHERE s.state = 'approved'
           AND s.date_to IS NOT NULL
         GROUP BY s.id, s.date_to, d.name->>'en_US', j.name->>'en_US'
        HAVING s.date_to < min(n.date_from) - 1
         ORDER BY 4, 5
    """)
    gaps = cr.fetchall()

    if not dead and not gaps:
        _logger.info(
            "l10n_ua_hr_base 19.0.1.4.0: no approved staffing line carries a "
            "past end date, so the new meaning of that field changes nothing")
        return

    if dead:
        # Who is standing on those positions, and would be calculated at zero.
        # Matched two ways on purpose: `hr_version.department_id` / `job_id`
        # are still empty on the versions whose position lived only in
        # `staffing_line_id` — l10n_ua_hr_contract fills them in its own
        # post-migration, which runs after this one. Counting by the position
        # alone would leave out exactly the employees this report is for.
        #
        # `current_version_id`, not `version_id`: the second is computed and
        # has no column of its own.
        line_ids = [row[0] for row in dead]
        by_line = {}
        pointer = _column_exists(cr, 'hr_version', 'staffing_line_id')
        cr.execute("""
            SELECT s.id, count(DISTINCT e.id)
              FROM hr_staffing_table s
              JOIN hr_version v
                ON (v.company_id = s.company_id
                    AND v.department_id = s.department_id
                    AND v.job_id = s.job_id)
                {pointer}
              JOIN hr_employee e
                ON e.current_version_id = v.id AND e.active
             WHERE s.id = ANY(%s)
               AND COALESCE(v.wage, 0) = 0
             GROUP BY s.id
        """.format(pointer='OR v.staffing_line_id = s.id' if pointer else ''),
            (line_ids,))
        by_line = dict(cr.fetchall())

        exposed = sum(by_line.values())
        _logger.warning(
            "l10n_ua_hr_base 19.0.1.4.0: %s position(s) have their newest "
            "approved line closed by a past date. From now on that reads as "
            "\"position discontinued\": those positions resolve to nothing, "
            "and %s employee(s) on them carry no wage of their own, so their "
            "next payslip is calculated at zero. Open a new approved line "
            "from the day the position continues, or clear the date where it "
            "never ended.",
            len(dead), exposed)
        for (line_id, company_id, department_id, job_id,
             date_to, department, job) in dead:
            _logger.warning(
                "  company %s, %s (id %s) / %s (id %s): line %s ends %s, "
                "%s employee(s) with no wage of their own",
                company_id, department or '?', department_id,
                job or '?', job_id, line_id, date_to,
                by_line.get(line_id, 0))

    if gaps:
        _logger.warning(
            "l10n_ua_hr_base 19.0.1.4.0: %s approved staffing line(s) end "
            "before the next line of the same position starts. Payslips "
            "recalculated for the months inside those gaps resolve to "
            "nothing.",
            len(gaps))
        for line_id, date_to, next_from, department, job in gaps:
            _logger.warning(
                "  %s / %s: line %s ends %s, next starts %s",
                department or '?', job or '?', line_id, date_to, next_from)


def migrate(cr, version):
    if not version:
        return

    _report_discontinued_positions(cr)

    # Grouped by the same columns the index is built on — ids, not names. Two
    # departments may legitimately share a name, and grouping by the name would
    # merge them into one report entry, sending the officer to look for a clash
    # the index is perfectly happy with. The names are carried along only to
    # make the message readable.
    cr.execute("""
        SELECT s.company_id,
               s.department_id,
               s.job_id,
               min(d.name->>'en_US'),
               min(j.name->>'en_US'),
               s.date_from,
               array_agg(s.id ORDER BY s.id)
        FROM hr_staffing_table s
        LEFT JOIN hr_department d ON d.id = s.department_id
        LEFT JOIN hr_job j ON j.id = s.job_id
        WHERE s.state = 'approved'
        GROUP BY s.company_id, s.department_id, s.job_id, s.date_from
        HAVING count(*) > 1
        ORDER BY 4, 5
    """)
    rows = cr.fetchall()
    if not rows:
        _logger.info(
            "l10n_ua_hr_base 19.0.1.4.0: no two approved staffing lines of a "
            "position share a start date, the unique index will be created")
        return

    _logger.warning(
        "l10n_ua_hr_base 19.0.1.4.0: %s positions hold several approved "
        "staffing lines starting on the same day. The unique index will NOT be "
        "created, and which line an employee resolves to stays undefined until "
        "this is fixed. Correct the dates or archive the surplus lines, then "
        "update the module again.",
        len(rows))
    for (company_id, department_id, job_id,
         department, job, date_from, ids) in rows:
        _logger.warning(
            "  company %s, %s (id %s) / %s (id %s) starting %s: ids %s",
            company_id, department or '?', department_id,
            job or '?', job_id, date_from, list(ids))
