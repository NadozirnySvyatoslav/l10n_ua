"""Report the gaps between the periods of a tariff grade.

From now on a gap cannot be saved, but one entered before is still in the
database, and it is found only when payroll stops in the middle of the month
it is computed for. They are listed here once, so that they are corrected
before that happens.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT g.company_id, c.name, g.grade, g.date_to,
               MIN(n.date_from) AS next_from
          FROM hr_tariff_grade g
          JOIN res_company c ON c.id = g.company_id
          JOIN hr_tariff_grade n
            ON n.company_id = g.company_id AND n.grade = g.grade
           AND n.date_from > g.date_from AND COALESCE(n.active, TRUE)
         WHERE g.date_to IS NOT NULL AND COALESCE(g.active, TRUE)
      GROUP BY g.company_id, c.name, g.grade, g.date_to
        HAVING MIN(n.date_from) > g.date_to + 1
      ORDER BY g.company_id, g.grade, g.date_to
    """)
    for company_id, company, grade, date_to, next_from in cr.fetchall():
        _logger.warning(
            'l10n_ua_hr_base 19.0.1.8.2: company "%s" (id %s), tariff grade '
            '%s: no rate in force between %s and %s. Payroll for that time '
            'stops until the periods meet.',
            company, company_id, grade, date_to, next_from)
