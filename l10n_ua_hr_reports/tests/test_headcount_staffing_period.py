"""The headcount report reads the staffing table of its own period.

`hr.version.staffing_line_id` answers for the version's period, and for the
ordinary open-ended Ukrainian contract that means today. Reading it here made
a report for March count the staff units the position carries in September —
and, since the field is computed and not stored, made every day of the month
share that one answer.
"""

from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestHeadcountStaffingPeriod(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = date.today()
        cls.long_ago = cls.today - relativedelta(years=2)
        cls.last_year = cls.today - relativedelta(years=1)
        cls.recently = cls.today - relativedelta(months=3)

        # An empty company of its own: the report counts everyone in the
        # company, so a populated database would make the totals depend on
        # records this test knows nothing about.
        cls.company = cls.env['res.company'].create(
            {'name': 'Headcount Staffing Co'})
        cls.env.user.company_ids = [(4, cls.company.id)]

        cls.department = cls.env['hr.department'].create({
            'name': 'Виробничий відділ',
            'company_id': cls.company.id,
        })
        cls.job = cls.env['hr.job'].create({
            'name': 'Оператор',
            'company_id': cls.company.id,
        })

        Staffing = cls.env['hr.staffing.table']
        # Half a staff unit back then, a whole one since. The later line is
        # already in force today, so reading "the current line" instead of the
        # line of the period is exactly what this pair detects.
        cls.old_line = Staffing.create({
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'date_from': cls.long_ago,
            'units': 0.5,
            'salary': 10000.0,
            'state': 'approved',
        })
        cls.new_line = Staffing.create({
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'date_from': cls.recently,
            'units': 1.0,
            'salary': 12000.0,
            'state': 'approved',
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Штатний Оператор',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })
        version = cls.employee.with_context(active_test=False).version_ids[:1]
        # `work_rate` is cleared on purpose: it takes precedence, and the
        # staffing table is only consulted when the version carries no rate of
        # its own.
        version.write({
            'contract_date_start': cls.long_ago,
            'contract_date_end': False,
            'work_rate': 0.0,
        })

        cls.report = cls.env['hr.report.headcount'].create({
            'year': cls.last_year.year,
            'month': str(cls.last_year.month),
            'company_id': cls.company.id,
        })

    def test_past_date_uses_the_line_of_that_period(self):
        headcount, fte = self.report._count_employees_on_date(self.last_year)
        self.assertEqual(
            fte, 0.5,
            'A day covered by the older line must be counted with the staff '
            'units of that line, not with the ones in force today')
        self.assertEqual(
            headcount, 0,
            'Half a staff unit is not a full head')

    def test_current_date_uses_the_line_in_force(self):
        headcount, fte = self.report._count_employees_on_date(self.today)
        self.assertEqual(fte, 1.0)
        self.assertEqual(headcount, 1)

    def test_days_of_one_report_do_not_share_one_answer(self):
        """The two dates must disagree — the bug made every day identical."""
        _, past_fte = self.report._count_employees_on_date(self.last_year)
        _, now_fte = self.report._count_employees_on_date(self.today)
        self.assertNotEqual(
            past_fte, now_fte,
            'The staffing line is resolved per date, so a month before the '
            'change and a month after it cannot produce the same FTE')

    def test_version_work_rate_still_wins(self):
        """The staffing table is a fallback, not an override."""
        version = self.employee.with_context(active_test=False).version_ids[:1]
        version.work_rate = 0.75
        _, fte = self.report._count_employees_on_date(self.last_year)
        self.assertEqual(fte, 0.75)
