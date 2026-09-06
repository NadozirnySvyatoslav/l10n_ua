"""Report the positions that would keep the new unique index out of the database.

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


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT s.company_id,
               d.name->>'en_US',
               j.name->>'en_US',
               s.date_from,
               array_agg(s.id ORDER BY s.id)
        FROM hr_staffing_table s
        LEFT JOIN hr_department d ON d.id = s.department_id
        LEFT JOIN hr_job j ON j.id = s.job_id
        WHERE s.state = 'approved'
        GROUP BY s.company_id, d.name->>'en_US', j.name->>'en_US', s.date_from
        HAVING count(*) > 1
        ORDER BY 2, 3
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
    for company_id, department, job, date_from, ids in rows:
        _logger.warning(
            "  company %s, %s / %s starting %s: ids %s",
            company_id, department or '?', job or '?', date_from, list(ids))
