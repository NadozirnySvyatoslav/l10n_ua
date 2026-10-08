"""Without payslips, the averages fall back on the staffing salary when the
version carries no wage — the ordinary case where salaries live in the
staffing table — as long as the company lets the staffing table stand in."""
from datetime import date, datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestFallbackWage(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.UAH')
        cls.department = cls.env['hr.department'].create({
            'name': 'Fallback Wage Department', 'company_id': cls.company.id})
        cls.job = cls.env['hr.job'].create({
            'name': 'Fallback Wage Job', 'company_id': cls.company.id,
            'department_id': cls.department.id})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Fallback Wage Employee', 'company_id': cls.company.id})
        cls.employee.current_version_id.write({
            'wage': 0.0, 'department_id': cls.department.id,
            'job_id': cls.job.id})
        cls.env['hr.staffing.table'].create({
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'date_from': date(2025, 1, 1),
            'units': 1.0,
            'salary': 29300.0,
            'state': 'approved',
        })
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Additional Leave (fallback test)',
            'ua_leave_category': 'annual_additional',
            'is_calendar_days': True,
            'is_paid': True,
            'requires_allocation': False,
            'company_id': cls.company.id,
        })

    def _leave(self):
        return self.env['hr.leave'].create({
            'name': 'Vacation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'date_from': datetime(2026, 6, 15, 8, 0, 0),
            'date_to': datetime(2026, 6, 21, 17, 0, 0),
        })

    def test_vacation_average_falls_back_on_the_staffing_salary(self):
        self.company.wage_from_staffing = 'both'
        self.assertAlmostEqual(self._leave()._calculate_average_salary(),
                               1000.0, places=2)

    def test_sick_average_falls_back_on_the_staffing_salary(self):
        self.company.wage_from_staffing = 'fallback'
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 15),
            'date_to': date(2026, 6, 20),
        })
        self.assertAlmostEqual(sick._calculate_average_salary(),
                               round(29300.0 / 30.44, 2), places=2)

    def test_a_company_that_refuses_the_fallback_gets_none(self):
        self.company.wage_from_staffing = 'none'
        self.assertEqual(self._leave()._calculate_average_salary(), 0.0)
