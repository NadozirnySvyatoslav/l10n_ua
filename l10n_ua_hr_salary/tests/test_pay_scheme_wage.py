"""Payroll reads the 1078 scheme salary from September 2026 only (#323).

CMU Resolution No 1078: from 1 September 2026 the salary of a teacher is the
base value × the coefficient of the position. A payslip for August keeps the
salary of the Unified Tariff Grid, the one for September takes the new one,
both from the staffing table, and a recalculation of August later on does not
pick up the September figure.
"""

from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPaySchemeWage(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.wage_from_staffing = 'both'
        cls.version.write({
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'wage': 0.0,
        })
        cls.teacher_top = cls.env.ref('l10n_ua_hr_base.pay_scheme_1078_ped_39')
        Staffing = cls.env['hr.staffing.table']
        common = {
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
            'units': 1.0,
            'state': 'approved',
        }
        Staffing.create({**common, 'date_from': date(2026, 1, 1), 'salary': 9500.0})
        Staffing.create({**common, 'date_from': date(2026, 9, 1),
                         'pay_scheme_line_id': cls.teacher_top.id})

    def _payslip(self, month):
        return self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2026, month, 1),
            'date_to': date(2026, month, 28),
            'company_id': self.company.id,
        })

    def test_august_keeps_the_grid_september_takes_the_scheme(self):
        september = self._payslip(9)
        august = self._payslip(8)
        self.assertEqual(september._get_effective_wage(self.version), 15020.0,
                         '28 885 × 0.52 = 15 020.20, rounded to 15 020')
        self.assertEqual(august._get_effective_wage(self.version), 9500.0,
                         'before 1 September the tariff-grid salary applies')

    def test_version_wage_from_scheme_is_paid_from_its_date(self):
        new = self.employee.create_version({
            'date_version': date(2026, 9, 1),
            'pay_scheme_line_id': self.teacher_top.id,
        })
        self.assertEqual(new.wage, 15020.0)
        self.assertEqual(self.version.wage, 0.0)
        self.assertEqual(self._payslip(9)._get_effective_wage(new), 15020.0)
        self.assertEqual(self._payslip(8)._get_effective_wage(self.version), 9500.0)
