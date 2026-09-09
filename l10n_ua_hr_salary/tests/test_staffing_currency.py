"""The staffing salary is converted by its own currency, not the version's.

Two mistakes, pointing opposite ways, both on the same figure:

* the payslip put the staffing salary through `salary_rate` — the rate of the
  currency the *version's* wage is denominated in. That rate says nothing about
  this money, and the fallback is only ever reached when the version carries no
  wage at all, so a version paid in USD turned a position of 20 000 UAH into
  830 000;
* the advance and the batch did not convert it at all, so a position priced in
  USD paid out as though the number were hryvnia.
"""

from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestStaffingCurrency(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref('base.USD')
        cls.env['res.currency.rate'].create({
            'name': '2026-01-01', 'currency_id': cls.usd.id,
            'company_id': cls.company.id, 'inverse_company_rate': 40.0,
        })
        cls.version.write({
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })

    def _line(self, salary, currency):
        return self.env['hr.staffing.table'].create({
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
            'date_from': date(2026, 1, 1),
            'units': 1.0,
            'salary': salary,
            'currency_id': currency.id,
            'state': 'approved',
        })

    def _payslip(self):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'company_id': self.company.id,
        })

    def test_hryvnia_line_is_not_multiplied_by_the_version_rate(self):
        """The case the fallback exists for: no wage, and a foreign currency.

        `salary_currency_id` describes a wage that is not there. Reading it as
        if it described the staffing line multiplied 20 000 by forty.
        """
        self.version.write({'wage': 0.0, 'salary_currency_id': self.usd.id})
        self._line(20000.0, self.uah)

        payslip = self._payslip()
        self.assertAlmostEqual(
            payslip._get_effective_wage(self.version), 20000.0, places=2,
            msg='A position priced in hryvnia stays in hryvnia whatever '
                'currency the version names for a wage it does not have')

    def test_foreign_line_is_converted(self):
        self.version.write({'wage': 0.0, 'salary_currency_id': False})
        self._line(500.0, self.usd)

        payslip = self._payslip()
        self.assertAlmostEqual(
            payslip._get_effective_wage(self.version), 20000.0, places=2,
            msg='500 USD at 40.0 is 20 000 UAH')

    def test_a_wage_on_the_version_still_uses_the_version_rate(self):
        """The fix must not touch the branch that was right."""
        self.version.write({'wage': 1000.0, 'salary_currency_id': self.usd.id})
        self._line(20000.0, self.uah)

        payslip = self._payslip()
        self.assertAlmostEqual(
            payslip._get_effective_wage(self.version), 40000.0, places=2,
            msg='1000 USD at 40.0 — the staffing line is not consulted at all')

    def test_advance_converts_the_staffing_currency(self):
        self.version.write({'wage': 0.0, 'salary_currency_id': False})
        self._line(500.0, self.usd)

        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'date': date(2026, 6, 15),
            'wage_percent': 50.0,
            'company_id': self.company.id,
        })
        self.assertAlmostEqual(
            advance.gross_amount, 10000.0, places=2,
            msg='500 USD at 40.0 is 20 000 UAH, half of which is 10 000')

    def test_batch_converts_the_staffing_currency(self):
        self.version.write({'wage': 0.0, 'salary_currency_id': False})
        self._line(500.0, self.usd)

        run = self.env['hr.salary.advance.run'].create({
            'name': 'Аванс за червень',
            'date': date(2026, 6, 15),
            'company_id': self.company.id,
            'wage_percent': 50.0,
        })
        self.assertAlmostEqual(
            run._get_employee_wage(self.employee), 20000.0, places=2)

    def test_a_line_without_a_rate_refuses_to_guess(self):
        """`_convert` answers 1.0 when it finds nothing; that is not an answer."""
        gbp = self.env.ref('base.GBP')
        self.version.write({'wage': 0.0, 'salary_currency_id': False})
        self._line(500.0, gbp)

        payslip = self._payslip()
        with self.assertRaises(Exception):
            payslip._get_effective_wage(self.version)
