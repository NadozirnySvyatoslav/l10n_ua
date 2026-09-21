"""Every company keeps its own PSP parameters; no record is shared.

`company_id` becomes required, so records without a company (shared by all
companies) are split before the schema update: every company that has no
record of its own for that period gets a copy, and the shared record is
dropped. No company is singled out: all of them get the same copy.

The xmlids of a dropped shared record go with it. The xmlids of the seeded
records bound to a company are removed by the post-migration, after the
19.0.1.4.4 post-migration has used them.

Done payslips of companies that had no parameters of their own are logged:
they were computed on another company's parameters or on the constants
hardcoded in the payslip code, and should be reviewed.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT c.id, c.name, count(s.id)
          FROM hr_payslip s
          JOIN res_company c ON c.id = s.company_id
         WHERE s.state = 'done'
           AND s.company_id NOT IN (
                SELECT company_id FROM hr_psp_parameters
                 WHERE company_id IS NOT NULL)
         GROUP BY c.id, c.name
    """)
    for company_id, name, count in cr.fetchall():
        _logger.warning(
            'l10n_ua_hr_salary 19.0.1.4.5: company "%s" (id %s) had no PSP '
            'parameters of its own; %s done payslips were computed on another '
            'company\'s parameters or on hardcoded constants and should be '
            'reviewed', name, company_id, count)

    cr.execute("SELECT count(*) FROM hr_psp_parameters WHERE company_id IS NULL")
    shared = cr.fetchone()[0]
    if not shared:
        return

    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'hr_psp_parameters'
           AND column_name NOT IN ('id', 'company_id')
    """)
    columns = [f'"{name}"' for (name,) in cr.fetchall()]

    cr.execute(f"""
        INSERT INTO hr_psp_parameters ({', '.join(columns)}, company_id)
        SELECT {', '.join(f'p.{c}' for c in columns)}, c.id
          FROM hr_psp_parameters p
         CROSS JOIN res_company c
         WHERE p.company_id IS NULL
           AND NOT EXISTS (
                SELECT 1 FROM hr_psp_parameters q
                 WHERE q.company_id = c.id
                   AND q.year = p.year AND q.date_from = p.date_from)
    """)
    copies = cr.rowcount

    cr.execute("""
        DELETE FROM ir_model_data
         WHERE model = 'hr.psp.parameters'
           AND res_id IN (SELECT id FROM hr_psp_parameters WHERE company_id IS NULL)
    """)
    cr.execute("DELETE FROM hr_psp_parameters WHERE company_id IS NULL")

    _logger.info(
        'l10n_ua_hr_salary 19.0.1.4.5: %s shared PSP parameter records split '
        'into %s per-company records', shared, copies)
