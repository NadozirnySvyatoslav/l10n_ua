"""The transferred wage falls back to the staffing table, as payroll does.

For Ukrainian practice a version carrying no `wage` is the normal case, not a
broken one: the salary lives in the staffing table and the card points at a
position. The payslip, the advance and the payment ledger all know that; the
transfer wizard did not, so such an employee moved to the new organisation
with a zero — silently, since the wizard showed 0 and the officer confirmed
the order on it.

The gate is `wage_from_staffing`, read from the company the person is leaving:
it is that company's pay being carried over, and the receiving one has decided
nothing about it yet.
"""

from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTransferWageFromStaffing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')

        cls.company_a = cls.env['res.company'].create(
            {'name': 'Staffing Source Co', 'currency_id': cls.uah.id})
        cls.company_b = cls.env['res.company'].create(
            {'name': 'Staffing Target Co', 'currency_id': cls.uah.id})
        cls.env.user.write({
            'company_ids': [(4, cls.company_a.id), (4, cls.company_b.id)]})

        cls.dept_a = cls.env['hr.department'].create(
            {'name': 'Source Dept', 'company_id': cls.company_a.id})
        cls.job_a = cls.env['hr.job'].create(
            {'name': 'Source Job', 'company_id': cls.company_a.id})
        cls.dept_b = cls.env['hr.department'].create(
            {'name': 'Target Dept', 'company_id': cls.company_b.id})
        cls.job_b = cls.env['hr.job'].create(
            {'name': 'Target Job', 'company_id': cls.company_b.id})

        cls.employee = cls.env['hr.employee'].with_company(
            cls.company_a).create({
                'name': 'Штатний Працівник',
                'company_id': cls.company_a.id,
            })
        # The version born with the employee is the one the wizard reads. It
        # carries the position and no wage — the case under test.
        cls.version = cls.employee.with_context(
            active_test=False).version_ids[:1]
        cls.version.write({
            'department_id': cls.dept_a.id,
            'job_id': cls.job_a.id,
            'wage': 0.0,
        })

    def _line(self, salary, date_from=date(2024, 1, 1), **overrides):
        vals = {
            'company_id': self.company_a.id,
            'department_id': self.dept_a.id,
            'job_id': self.job_a.id,
            'units': 1.0,
            'salary': salary,
            # Stated, not left to the default: `currency_id` defaults to the
            # currency of the company in the switcher, which is not the one
            # the line belongs to. The staffing table means the money of its
            # own company here.
            'currency_id': self.company_a.currency_id.id,
            'date_from': date_from,
            'state': 'approved',
        }
        vals.update(overrides)
        return self.env['hr.staffing.table'].create(vals)

    def _wizard(self, **overrides):
        vals = {
            'source_employee_id': self.employee.id,
            'source_company_id': self.company_a.id,
            'target_company_id': self.company_b.id,
            'dismissal_date': date(2026, 4, 30),
            'hire_date': date(2026, 5, 1),
            'new_department_id': self.dept_b.id,
            'new_job_id': self.job_b.id,
            'copy_wage': True,
        }
        vals.update(overrides)
        return self.env['hr.employee.transfer.wizard'].create(vals)

    def test_the_staffing_salary_travels_when_the_version_has_none(self):
        """Оклад із розпису, а не нуль — це і був баг #303."""
        self._line(18000.0)

        self.assertAlmostEqual(self._wizard().new_wage, 18000.0, places=2)

    def test_a_wage_on_the_version_wins(self):
        """Розпис — фолбек, а не заміна: свій оклад версії лишається своїм."""
        self._line(18000.0)
        self.version.write({'wage': 25000.0})

        self.assertAlmostEqual(self._wizard().new_wage, 25000.0, places=2)

    def test_the_line_in_force_on_the_hire_date_is_used(self):
        """Переведення оцінюється за розписом свого дня, а не найновішим."""
        self._line(18000.0, date_from=date(2024, 1, 1))
        self._line(30000.0, date_from=date(2026, 6, 1))

        self.assertAlmostEqual(
            self._wizard().new_wage, 18000.0, places=2,
            msg='Прийняття 2026-05-01 — рядок від 2026-06-01 ще не діє')

    def test_a_draft_line_is_not_a_salary(self):
        self._line(18000.0, state='draft')

        self.assertEqual(self._wizard().new_wage, 0.0)

    def test_the_gate_of_the_source_company_decides(self):
        """Політика оплати — компанії, з якої переводять."""
        self._line(18000.0)
        self.company_a.wage_from_staffing = 'none'

        self.assertEqual(self._wizard().new_wage, 0.0)

    def test_suggest_only_is_not_a_fallback(self):
        """`suggest` заповнює картку при виборі посади, і тільки."""
        self._line(18000.0)
        self.company_a.wage_from_staffing = 'suggest'

        self.assertEqual(self._wizard().new_wage, 0.0)

    def test_the_target_company_does_not_decide(self):
        """Компанія призначення про цей оклад ще нічого не вирішувала."""
        self._line(18000.0)
        self.company_a.wage_from_staffing = 'both'
        self.company_b.wage_from_staffing = 'none'

        self.assertAlmostEqual(self._wizard().new_wage, 18000.0, places=2)

    def test_the_staffing_salary_is_converted_to_the_target_currency(self):
        """Через розпис оклад теж не має міняти валюту мовчки."""
        self.company_b.currency_id = self.usd
        self.env['res.currency.rate'].create({
            'name': '2026-01-01', 'currency_id': self.usd.id,
            'company_id': self.company_b.id, 'inverse_company_rate': 40.0,
        })
        self._line(40000.0)

        self.assertAlmostEqual(self._wizard().new_wage, 1000.0, places=2)
