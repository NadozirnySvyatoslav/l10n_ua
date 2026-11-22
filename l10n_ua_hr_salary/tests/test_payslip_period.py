"""Payslip follows its own period: partial month, allowances, alimony.

June 2025 has 21 working days.
"""

from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPayslipPeriod(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salary_type = cls.env['hr.accrual.type'].search(
            [('code', '=', 'SALARY')], limit=1)

    def _hire(self, start, end=False, wage=21000):
        employee = self.env['hr.employee'].create({
            'name': f'Працівник з {start}', 'company_id': self.company.id,
        })
        version = self.env['hr.version'].create({
            'employee_id': employee.id,
            'contract_date_start': start,
            'contract_date_end': end,
            'date_version': start,
            'wage': wage,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': self.company.id,
        })
        employee.write({'current_version_id': version.id})
        return employee

    def _compute(self, employee):
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'company_id': self.company.id,
        })
        slip.action_compute_sheet()
        return slip

    def _salary(self, slip):
        return sum(slip.accrual_ids.filtered(
            lambda a: a.accrual_type_id == self.salary_type).mapped('amount'))

    def test_hired_mid_month_without_timesheet(self):
        """No timesheet: the norm is the month, the worked days only those
        under contract — 11 of 21 for a hire on 16 June."""
        slip = self._compute(self._hire(date(2025, 6, 16)))
        self.assertEqual(slip.scheduled_days, 21)
        self.assertEqual(slip.worked_days, 11)
        self.assertAlmostEqual(self._salary(slip), 11000.0, places=2)

    def test_dismissed_mid_month_without_timesheet(self):
        slip = self._compute(self._hire(date(2024, 1, 1), date(2025, 6, 10)))
        self.assertEqual(slip.worked_days, 7)
        self.assertAlmostEqual(self._salary(slip), 7000.0, places=2)

    def test_hired_mid_month_with_timesheet(self):
        """With the attendance sheet the payslip takes its norm and worked
        days: the norm stays the month's 21 days, not the 11 worked."""
        if 'hr.timesheet' not in self.env:
            self.skipTest('l10n_ua_hr_attendance_sheet не встановлено')
        employee = self._hire(date(2025, 6, 16))
        sheet = self.env['hr.timesheet'].create({
            'year': 2025, 'month': '6', 'company_id': self.company.id,
        })
        sheet.action_generate_lines()
        sheet.action_confirm()
        slip = self._compute(employee)
        self.assertEqual(slip.scheduled_days, 21)
        self.assertEqual(slip.worked_days, 11)
        self.assertAlmostEqual(self._salary(slip), 11000.0, places=2)

    def test_allowance_judged_by_payslip_period(self):
        """An allowance that ended long ago still belongs to the payslip of
        its own period, and one starting later does not."""
        allowance_type = self.env['hr.allowance.type'].search([], limit=1) \
            or self.env['hr.allowance.type'].create({'name': 'Надбавка (тест)'})
        Allowance = self.env['hr.version.allowance']
        past = Allowance.create({
            'version_id': self.version.id,
            'allowance_type_id': allowance_type.id,
            'calculation_method': 'fixed',
            'amount': 1000.0,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 6, 30),
        })
        Allowance.create({
            'version_id': self.version.id,
            'allowance_type_id': allowance_type.id,
            'calculation_method': 'fixed',
            'amount': 777.0,
            'date_from': date(2025, 7, 1),
        })
        self.assertFalse(past.is_active, 'pre-condition: ended before today')
        slip = self._compute(self.employee)
        allowance_lines = slip.accrual_ids.filtered(
            lambda a: a.accrual_type_id.code == 'ALLOWANCE')
        self.assertEqual(allowance_lines.mapped('amount'), [1000.0])
