"""Tariff grades per company and period, with hourly rates only.

Until now `hr.tariff.grade` was one list for the whole database, with a
monthly salary or an hourly rate that payroll multiplied by the coefficient,
although the amounts entered already carried the progression. Nothing is
recalculated here, only moved:

* a grade used by versions or job positions goes to each company using it, in
  force from the company's earliest version; the first company keeps the
  record, every other one gets a copy and its versions and positions are
  pointed at it. Grades with an amount that nobody uses go to every company;
* grades nobody uses and nobody put an amount on are the old seed data and are
  removed: every company gets the typical set from the template when the data
  is loaded;
* the form showed only the monthly salary field, so hourly rates were typed
  into it. Where a grade has no hourly rate, its amount is taken as the hourly
  rate and reported in the log to be checked: monthly salaries belong to the
  staffing table.
"""

import logging

from odoo import fields
from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

PREFIX = 'l10n_ua_hr_base 19.0.1.8.1'


def migrate(cr, version):
    if not version or not table_exists(cr, 'hr_tariff_grade'):
        return
    if column_exists(cr, 'hr_tariff_grade', 'company_id'):
        return
    for column in ('company_id INTEGER', 'date_from DATE', 'date_to DATE'):
        cr.execute(f'ALTER TABLE hr_tariff_grade ADD COLUMN {column}')
    # Grade numbers now repeat from company to company and period to period.
    cr.execute("ALTER TABLE hr_tariff_grade DROP CONSTRAINT IF EXISTS hr_tariff_grade_grade_uniq")
    # The seed records either go or become one company's own grades.
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'l10n_ua_hr_base' AND model = 'hr.tariff.grade'
    """)
    _from_shared_list(cr)


def _from_shared_list(cr):
    has_salary = column_exists(cr, 'hr_tariff_grade', 'min_salary')
    salary = 'COALESCE(min_salary, 0)' if has_salary else '0'
    cr.execute(f"""
        SELECT id, grade, COALESCE(hourly_rate, 0) AS hourly_rate,
               {salary} AS min_salary
          FROM hr_tariff_grade
    """)
    grades = cr.dictfetchall()
    for g in grades:
        if g['min_salary'] and not g['hourly_rate']:
            cr.execute("UPDATE hr_tariff_grade SET hourly_rate = %s WHERE id = %s",
                       (g['min_salary'], g['id']))
            _logger.warning(
                '%s: tariff grade %s had only a monthly salary of %s; it is now '
                'its hourly rate. Check it: monthly salaries belong to the '
                'staffing table.', PREFIX, g['grade'], g['min_salary'])

    version_links = column_exists(cr, 'hr_version', 'tariff_grade_id')
    used = """
        SELECT company_id, tariff_grade_id FROM hr_job
         WHERE tariff_grade_id IS NOT NULL AND company_id IS NOT NULL
    """ + ("""
        UNION SELECT company_id, tariff_grade_id FROM hr_version
         WHERE tariff_grade_id IS NOT NULL AND company_id IS NOT NULL
    """ if version_links else "")
    cr.execute(f"SELECT DISTINCT company_id FROM ({used}) u ORDER BY company_id")
    companies = [company_id for (company_id,) in cr.fetchall()]
    if not companies:
        cr.execute("""
            DELETE FROM hr_tariff_grade
             WHERE COALESCE(hourly_rate, 0) = 0
               AND id NOT IN (SELECT tariff_grade_id FROM hr_job
                               WHERE tariff_grade_id IS NOT NULL)
        """)
        cr.execute("SELECT 1 FROM hr_tariff_grade LIMIT 1")
        if not cr.fetchone():
            return
        cr.execute("SELECT id FROM res_company ORDER BY id")
        companies = [company_id for (company_id,) in cr.fetchall()]

    cr.execute("""
        SELECT company_id, MIN(date_version) FROM hr_version
         WHERE company_id IS NOT NULL GROUP BY company_id
    """)
    earliest = dict(cr.fetchall())
    today = fields.Date.today()
    for index, company_id in enumerate(companies):
        date_from = earliest.get(company_id) or today
        if index == 0:
            cr.execute("UPDATE hr_tariff_grade SET company_id = %s, date_from = %s",
                       (company_id, date_from))
            continue
        cr.execute("""
            INSERT INTO hr_tariff_grade
                (company_id, date_from, name, grade, coefficient, hourly_rate,
                 active, create_date, write_date)
            SELECT %s, %s, name, grade, coefficient, hourly_rate,
                   active, NOW() AT TIME ZONE 'UTC',
                   NOW() AT TIME ZONE 'UTC'
              FROM hr_tariff_grade WHERE company_id = %s
         RETURNING id, grade
        """, (company_id, date_from, companies[0]))
        for new_id, grade in cr.fetchall():
            for table in ['hr_job'] + (['hr_version'] if version_links else []):
                cr.execute(f"""
                    UPDATE {table} t SET tariff_grade_id = %s
                      FROM hr_tariff_grade old
                     WHERE t.company_id = %s AND t.tariff_grade_id = old.id
                       AND old.company_id = %s AND old.grade = %s
                """, (new_id, company_id, companies[0], grade))
    _logger.info('%s: tariff grades given to %s company(ies).',
                 PREFIX, len(companies))
