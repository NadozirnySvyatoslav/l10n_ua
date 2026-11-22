"""Vacation pay, sick pay and compensation on dismissal in the payslip
(#630), and the norm by the employee's own schedule without a timesheet
(#631).

They need l10n_ua_hr_holidays, which this module does not depend on: the
tests are skipped when it is not installed. June 2025 has 21 weekdays.
"""
from datetime import date

from odoo import Command
from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestAbsenceAccruals(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.has_holidays = 'hr.sick.leave' in cls.env
        if cls.has_holidays:
            cls.annual = cls.env.ref(
                'l10n_ua_hr_holidays.leave_type_annual_basic')
            cls.annual.write({'requires_experience': False,
                              'annual_days': 24, 'is_transferable': True})

    def setUp(self):
        super().setUp()
        if not self.has_holidays:
            self.skipTest('l10n_ua_hr_holidays is not installed')

    def _type(self, code):
        return self.env['hr.accrual.type'].search([('code', '=', code)], limit=1)

    def _lines(self, slip, code):
        return slip.accrual_ids.filtered(
            lambda a: a.accrual_type_id.code == code)

    def _slip(self, employee=None, start=date(2025, 6, 1), end=date(2025, 6, 30)):
        slip = self.env['hr.payslip'].create({
            'employee_id': (employee or self.employee).id,
            'date_from': start,
            'date_to': end,
            'company_id': self.company.id,
        })
        slip.action_compute_sheet()
        return slip

    def _leave(self, start, end, average=1000.0, employee=None, leave_type=None):
        leave = self.env['hr.leave'].create({
            'name': 'Щорічна відпустка',
            'employee_id': (employee or self.employee).id,
            'work_entry_type_id': (leave_type or self.annual).id,
            'request_date_from': start,
            'request_date_to': end,
            'average_daily_salary': average,
        })
        leave.sudo().state = 'validate'
        return leave

    def _sick(self, start, end, **vals):
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': start,
            'date_to': end,
            'sick_leave_type': 'illness',
            'insurance_experience_years': 10,
            'average_daily_salary': 800.0,
            **vals,
        })
        sick.action_confirm()
        return sick

    def test_vacation_pay_accrued_from_leave(self):
        leave = self._leave(date(2025, 6, 9), date(2025, 6, 13))
        slip = self._slip()
        vacation = self._lines(slip, 'VACATION')
        self.assertEqual(len(vacation), 1)
        self.assertEqual(vacation.quantity, 5)
        self.assertAlmostEqual(vacation.amount, 5000.0, places=2)
        self.assertEqual(vacation.source_ref, leave)
        self.assertTrue(vacation.is_auto_generated)
        # The vacation days are not worked: no salary for them on top.
        self.assertEqual(slip.worked_days, 16)
        self.assertAlmostEqual(self._lines(slip, 'SALARY').amount,
                               round(25000 * 16 / 21, 2), places=2)
        # Taxed like the rest of the income.
        self.assertAlmostEqual(slip.military_tax_base, slip.gross_salary,
                               places=2)
        # Recomputing replaces the line, it does not add another one.
        slip.action_compute_sheet()
        self.assertEqual(len(self._lines(slip, 'VACATION')), 1)

    def test_vacation_pay_not_accrued_twice(self):
        self._leave(date(2025, 6, 9), date(2025, 6, 13))
        self._slip()
        second = self._slip()
        self.assertFalse(self._lines(second, 'VACATION'))

    def test_manual_vacation_line_wins(self):
        self._leave(date(2025, 6, 9), date(2025, 6, 13))
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
            'company_id': self.company.id,
            'accrual_ids': [Command.create({
                'accrual_type_id': self._type('VACATION').id,
                'amount': 4321.0,
            })],
        })
        slip.action_compute_sheet()
        vacation = self._lines(slip, 'VACATION')
        self.assertEqual(len(vacation), 1)
        self.assertEqual(vacation.amount, 4321.0)

    def test_vacation_starting_in_other_month_not_accrued(self):
        self._leave(date(2025, 5, 26), date(2025, 6, 6))
        self.assertFalse(self._lines(self._slip(), 'VACATION'))

    def test_unpaid_leave_not_paid(self):
        unpaid = self.env.ref('l10n_ua_hr_holidays.leave_type_unpaid')
        self._leave(date(2025, 6, 9), date(2025, 6, 13), leave_type=unpaid)
        slip = self._slip()
        self.assertFalse(self._lines(slip, 'VACATION'))
        self.assertEqual(slip.worked_days, 16)

    def test_sick_pay_split_company_and_fss(self):
        sick = self._sick(date(2025, 6, 2), date(2025, 6, 11))
        slip = self._slip()
        employer = self._lines(slip, 'SICK_EMP')
        fss = self._lines(slip, 'SICK_FSS')
        self.assertEqual(employer.quantity, 5)
        self.assertAlmostEqual(employer.amount, 4000.0, places=2)
        self.assertEqual(fss.quantity, 5)
        self.assertAlmostEqual(fss.amount, 4000.0, places=2)
        self.assertEqual(employer.source_ref, sick)
        # 8 weekdays on sick leave.
        self.assertEqual(slip.worked_days, 13)
        # The flags of the accrual types decide the taxes: the FSS part is
        # outside the ESV base of the payslip, the company part inside.
        esv_lines = slip.accrual_ids.filtered('is_esv_base')
        self.assertIn(employer, esv_lines)
        self.assertNotIn(fss, esv_lines)
        self.assertFalse(self._lines(self._slip(), 'SICK_EMP'))

    def test_sick_pay_priced_when_not_calculated(self):
        self._sick(date(2025, 6, 2), date(2025, 6, 4), average_daily_salary=0.0)
        slip = self._slip()
        employer = self._lines(slip, 'SICK_EMP')
        # No payslips before: the wage over 30.44 days, at 100 %.
        self.assertAlmostEqual(employer.rate, round(25000 / 30.44, 2), places=2)
        self.assertAlmostEqual(employer.amount, round(3 * 25000 / 30.44, 2),
                               places=1)

    def test_pregnancy_is_maternity_benefit(self):
        self._sick(date(2025, 6, 2), date(2025, 6, 11),
                   sick_leave_type='pregnancy')
        slip = self._slip()
        self.assertFalse(self._lines(slip, 'SICK_EMP'))
        self.assertFalse(self._lines(slip, 'SICK_FSS'))
        self.assertAlmostEqual(self._lines(slip, 'MATERNITY').amount, 8000.0,
                               places=2)

    def _dismissed(self, opening=None):
        employee = self.env['hr.employee'].create({
            'name': 'Звільнений 30.06.2025', 'company_id': self.company.id,
        })
        version = self.env['hr.version'].create({
            'employee_id': employee.id,
            'contract_date_start': date(2017, 3, 1),
            'contract_date_end': date(2025, 6, 30),
            'date_version': date(2017, 3, 1),
            'wage': 25000,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': self.company.id,
        })
        employee.write({'current_version_id': version.id})
        if opening:
            employee.write({
                'l10n_ua_vacation_opening_date': opening[0],
                'l10n_ua_vacation_opening_days': opening[1],
            })
        return employee

    def test_compensation_on_dismissal_without_history(self):
        """Hired in 2017, nothing recorded: only the days of the last work
        year earned up to the dismissal (24 × 122 / 365), not eight years."""
        slip = self._slip(self._dismissed())
        comp = self._lines(slip, 'COMP_VAC')
        self.assertEqual(len(comp), 1)
        self.assertEqual(comp.quantity, round(24 * 122 / 365, 2))
        self.assertAlmostEqual(comp.rate, round(25000 / 29.3, 2), places=2)
        self.assertAlmostEqual(comp.amount, round(comp.quantity * comp.rate, 2),
                               places=2)
        self.assertEqual(comp.source_ref._name, 'hr.vacation.balance')
        self.assertFalse(self._lines(self._slip(comp.source_ref.employee_id),
                                     'COMP_VAC'))

    def test_compensation_uses_opening_balance(self):
        employee = self._dismissed(opening=(date(2025, 3, 1), 10))
        comp = self._lines(self._slip(employee), 'COMP_VAC')
        self.assertEqual(comp.quantity, round(10 + 24 * 122 / 365, 2))

    def test_no_compensation_without_dismissal(self):
        self.assertFalse(self._lines(self._slip(), 'COMP_VAC'))

    def test_norm_by_own_six_day_schedule(self):
        six_day = self.env['resource.calendar'].create({
            'name': 'Шестиденка (листок)',
            'company_id': self.company.id,
            'attendance_ids': [Command.clear()] + [
                Command.create({
                    'dayofweek': str(dow),
                    'duration_hours': 7.0 if dow < 5 else 5.0,
                    'hour_from': 0, 'hour_to': 0,
                }) for dow in range(6)
            ],
        })
        self.version.resource_calendar_id = six_day
        slip = self._slip()
        # June 2025: 21 weekdays and 4 Saturdays.
        self.assertEqual(slip.scheduled_days, 25)
        self.assertEqual(slip.worked_days, 25)
        self.assertAlmostEqual(slip.scheduled_hours, 21 * 7.0 + 4 * 5.0)
        self.assertAlmostEqual(self._lines(slip, 'SALARY').amount, 25000.0,
                               places=2)
