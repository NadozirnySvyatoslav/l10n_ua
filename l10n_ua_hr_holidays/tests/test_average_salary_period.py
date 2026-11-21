"""Середня заробітна плата для відпустки й лікарняного (Порядок №100).

- без розрахункових листків оклад береться з версії, а коли там нуль — зі
  штатного розпису, де він в українській практиці й живе;
- працівник, що відпрацював менше 12 місяців, отримує середню за фактично
  відпрацьовані місяці, а не їхній заробіток, розмазаний на рік.
"""
from datetime import date, datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestAverageSalaryPeriod(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.currency_id = cls.env.ref('base.UAH')
        cls.department = cls.env['hr.department'].create({
            'name': 'Відділ (середня)', 'company_id': cls.company.id,
        })
        cls.job = cls.env['hr.job'].create({
            'name': 'Посада (середня)', 'company_id': cls.company.id,
            'department_id': cls.department.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Працівник за штатним розписом',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })
        cls.version = cls.employee.current_version_id
        cls.version.write({
            'wage': 0.0,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })
        cls.env['hr.staffing.table'].create({
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'date_from': date(2025, 1, 1),
            'units': 1.0,
            'salary': 20000.0,
            'state': 'approved',
        })
        cls.company.wage_from_staffing = 'both'
        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_AVG_PERIOD_1',
            'name': 'Щорічна основна (середня)',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
        })

    def _leave(self):
        return self.env['hr.leave'].create({
            'name': 'Відпустка',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type.id,
            'date_from': datetime(2026, 6, 15, 8, 0, 0),
            'date_to': datetime(2026, 6, 21, 17, 0, 0),
        })

    def test_vacation_fallback_uses_staffing_salary(self):
        self.assertAlmostEqual(
            self._leave()._calculate_average_salary(),
            round(20000 / 29.3, 2), places=2)

    def test_sick_leave_fallback_uses_staffing_salary(self):
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, 6, 15),
            'date_to': date(2026, 6, 20),
        })
        self.assertAlmostEqual(
            sick._calculate_average_salary(), round(20000 / 30.44, 2), places=2)

    def test_vacation_average_over_months_actually_worked(self):
        """Three months of earnings are averaged over those three months."""
        if 'hr.payslip' not in self.env:
            self.skipTest('l10n_ua_hr_salary не встановлено — листків немає')
        accrual_type = self.env['hr.accrual.type'].search(
            [('category', '=', 'wage')], limit=1)
        for month_start, month_end in ((date(2026, 3, 1), date(2026, 3, 31)),
                                       (date(2026, 4, 1), date(2026, 4, 30)),
                                       (date(2026, 5, 1), date(2026, 5, 31))):
            slip = self.env['hr.payslip'].create({
                'employee_id': self.employee.id,
                'date_from': month_start,
                'date_to': month_end,
                'company_id': self.company.id,
            })
            self.env['hr.payslip.accrual'].create({
                'payslip_id': slip.id,
                'accrual_type_id': accrual_type.id,
                'quantity': 1,
                'rate': 30000,
                'amount': 30000,
            })
            slip.write({'state': 'done'})
        holidays = len([
            h for h in self.env['resource.calendar.leaves'].search([
                ('resource_id', '=', False),
                ('date_from', '>=', date(2026, 3, 1)),
                ('date_to', '<=', date(2026, 5, 31)),
            ]) if date(2026, 3, 1) <= h.date_from.date() <= date(2026, 5, 31)
        ])
        self.assertAlmostEqual(
            self._leave()._calculate_average_salary(),
            round(90000 / (92 - holidays), 2), places=2)
