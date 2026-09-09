"""The transferred wage arrives in the currency it is labelled with.

`new_wage` is declared with `currency_field='currency_id'`, and `currency_id`
is the target company's. The figure it was filled from is not: `wage` lives in
the version's own currency — `salary_currency_id` for a contract in foreign
money, otherwise the source company's. Carrying the number across verbatim put
someone else's currency behind the target's label: a wage of 1 000 USD became
1 000 UAH in the new company, and a transfer between companies on different
currencies moved unconverted.
"""

from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTransferWageCurrency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.uah = cls.env.ref('base.UAH')
        cls.usd = cls.env.ref('base.USD')

        cls.company_a = cls.env['res.company'].create(
            {'name': 'Wage Source Co', 'currency_id': cls.uah.id})
        cls.company_b = cls.env['res.company'].create(
            {'name': 'Wage Target Co', 'currency_id': cls.uah.id})
        cls.env.user.write({
            'company_ids': [(4, cls.company_a.id), (4, cls.company_b.id)]})

        cls.env['res.currency.rate'].create({
            'name': '2026-01-01', 'currency_id': cls.usd.id,
            'company_id': cls.company_a.id, 'inverse_company_rate': 40.0,
        })

        cls.dept_b = cls.env['hr.department'].create(
            {'name': 'Target Dept', 'company_id': cls.company_b.id})
        cls.job_b = cls.env['hr.job'].create(
            {'name': 'Target Job', 'company_id': cls.company_b.id})

        cls.employee = cls.env['hr.employee'].with_company(
            cls.company_a).create({
                'name': 'Валютний Працівник',
                'company_id': cls.company_a.id,
            })
        cls.version = cls.employee.with_context(
            active_test=False).version_ids[:1]

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

    def test_a_foreign_wage_is_converted(self):
        """1 000 USD is 40 000 UAH in the new company, not 1 000."""
        if 'salary_currency_id' not in self.version._fields:
            self.skipTest('salary currency needs l10n_ua_hr_salary')
        self.version.write({'wage': 1000.0, 'salary_currency_id': self.usd.id})

        self.assertAlmostEqual(self._wizard().new_wage, 40000.0, places=2)

    def test_a_hryvnia_wage_travels_unchanged(self):
        """Same currency on both sides: nothing to convert, nothing to move."""
        self.version.write({'wage': 25000.0})

        self.assertAlmostEqual(self._wizard().new_wage, 25000.0, places=2)

    def test_companies_on_different_currencies_convert(self):
        self.company_b.currency_id = self.usd
        self.env['res.currency.rate'].create({
            'name': '2026-01-01', 'currency_id': self.usd.id,
            'company_id': self.company_b.id, 'inverse_company_rate': 40.0,
        })
        self.version.write({'wage': 40000.0})

        self.assertAlmostEqual(self._wizard().new_wage, 1000.0, places=2)

    def test_not_copying_the_wage_leaves_nothing_behind(self):
        self.version.write({'wage': 25000.0})

        self.assertEqual(self._wizard(copy_wage=False).new_wage, 0.0)

    def test_the_rate_of_the_hire_date_is_used(self):
        """A transfer prepared in advance is priced on the day it happens."""
        if 'salary_currency_id' not in self.version._fields:
            self.skipTest('salary currency needs l10n_ua_hr_salary')
        self.env['res.currency.rate'].create({
            'name': '2026-05-01', 'currency_id': self.usd.id,
            'company_id': self.company_a.id, 'inverse_company_rate': 45.0,
        })
        self.version.write({'wage': 1000.0, 'salary_currency_id': self.usd.id})

        self.assertAlmostEqual(
            self._wizard().new_wage, 45000.0, places=2,
            msg='The hire date is 2026-05-01, so the May rate applies')
