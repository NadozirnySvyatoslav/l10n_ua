"""An advance obeys the same staffing-table setting as the payslip.

`wage_from_staffing` says whether a company lets the staffing table stand in
for a wage the version does not carry. The payslip asks it; the advance and the
advance batch did not, and took the staffing salary regardless. A company that
had turned the fallback off therefore paid an advance against a payslip that
calculates zero — and then deducted that advance from it, leaving a negative
net.
"""

from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestAdvanceStaffingFallback(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payment_date = date(2025, 6, 15)

        # The shared fixture builds the version without a position; on a real
        # card the two fields come from the employee form. The staffing table
        # is resolved from them, so the test has to state them.
        cls.version.write({
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })

        cls.staffing = cls.env['hr.staffing.table'].create({
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'date_from': date(2025, 1, 1),
            'units': 1.0,
            'salary': 20000.0,
            'state': 'approved',
        })
        # The whole point of the fallback: a version that carries no wage of
        # its own, which is the ordinary case on a database keeping a staffing
        # table.
        cls.version.wage = 0.0

    def _gross(self, setting):
        """Gross of a fresh advance under the given company setting.

        Created after the setting is written on purpose: `gross_amount` does
        not depend on it, by the same decision that keeps a confirmed advance
        from moving when the staffing table is revised.
        """
        self.company.wage_from_staffing = setting
        advance = self.env['hr.salary.advance'].create({
            'employee_id': self.employee.id,
            'date': self.payment_date,
            'wage_percent': 50.0,
            'company_id': self.company.id,
        })
        return advance.gross_amount

    def test_fallback_allowed_takes_the_staffing_salary(self):
        self.assertEqual(self._gross('both'), 10000.0)
        self.assertEqual(self._gross('fallback'), 10000.0)

    def test_fallback_refused_pays_nothing(self):
        self.assertEqual(
            self._gross('none'), 0.0,
            'A company that does not use the staffing table for wages must '
            'not have an advance calculated from it')

    def test_suggest_only_is_not_a_fallback(self):
        self.assertEqual(
            self._gross('suggest'), 0.0,
            '"Suggest" fills the wage in when a position is picked; it does '
            'not stand in for a wage that was never set')

    def test_the_batch_obeys_the_same_setting(self):
        run = self.env['hr.salary.advance.run'].create({
            'name': 'Аванс за червень',
            'date': self.payment_date,
            'company_id': self.company.id,
            'wage_percent': 50.0,
        })
        self.company.wage_from_staffing = 'both'
        self.assertEqual(run._get_employee_wage(self.employee), 20000.0)

        self.company.wage_from_staffing = 'none'
        self.assertEqual(
            run._get_employee_wage(self.employee), 0.0,
            'The batch must not read the staffing table where the payslip '
            'will not')

    def test_a_wage_on_the_version_is_unaffected(self):
        """The gate guards the fallback only, never a wage that exists."""
        self.version.wage = 30000.0
        try:
            self.assertEqual(self._gross('none'), 15000.0)
        finally:
            self.version.wage = 0.0
