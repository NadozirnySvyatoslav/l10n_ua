"""The days away are paid by their own accruals, in the month of each day.

Since the norm of a payslip is the month's, the salary no longer pays for the
days of a vacation or a sickness; their vacation pay and benefits do.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestAbsencePay(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.sick.leave' not in cls.env:
            return
        LeaveType = cls.env['hr.leave.type']
        common = {'is_calendar_days': True, 'requires_allocation': False,
                  'company_id': cls.company.id}
        cls.vacation_type = LeaveType.create(dict(
            common, name='Additional Leave (absence pay test)',
            ua_leave_category='annual_additional', is_paid=True))
        cls.sick_type = LeaveType.create(dict(
            common, name='Sick Leave (absence pay test)',
            ua_leave_category='sick', is_paid=True))
        cls.version.tariff_grade_id = False

    def setUp(self):
        super().setUp()
        if 'hr.sick.leave' not in self.env:
            self.skipTest('l10n_ua_hr_holidays is not installed')

    def _leave(self, leave_type, day_from, day_to):
        leave = self.env['hr.leave'].create({
            'name': 'Absence',
            'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': day_from,
            'request_date_to': day_to,
        })
        leave._action_validate()
        return leave

    def _payslip(self, month_from, month_to):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': month_from, 'date_to': month_to,
        })
        slip.action_compute_sheet()
        return slip

    def _of_type(self, slip, code):
        return slip.accrual_ids.filtered(lambda a: a.accrual_type_id.code == code)

    def _days_less_holidays(self, slip, first, last):
        holidays = slip._public_holiday_dates()
        return sum(1 for n in range((last - first).days + 1)
                   if first + relativedelta(days=n) not in holidays)

    def test_a_vacation_across_two_months_is_paid_in_each(self):
        leave = self._leave(self.vacation_type, date(2025, 7, 28), date(2025, 8, 10))
        leave.average_daily_salary = 1000.0
        july = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        august = self._payslip(date(2025, 8, 1), date(2025, 8, 31))
        in_july = self._days_less_holidays(july, date(2025, 7, 28), date(2025, 7, 31))
        in_august = self._days_less_holidays(august, date(2025, 8, 1), date(2025, 8, 10))
        self.assertAlmostEqual(self._of_type(july, 'VACATION').amount,
                               1000.0 * in_july, places=2)
        self.assertAlmostEqual(self._of_type(august, 'VACATION').amount,
                               1000.0 * in_august, places=2)
        self.assertAlmostEqual(
            sum(self._of_type(july | august, 'VACATION').mapped('amount')),
            leave.vacation_pay_amount, places=2)

    def test_the_average_is_fixed_when_the_vacation_is_first_paid(self):
        leave = self._leave(self.vacation_type, date(2025, 7, 14), date(2025, 7, 20))
        self.assertFalse(leave.average_daily_salary)
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertTrue(leave.average_daily_salary)
        self.assertAlmostEqual(
            self._of_type(slip, 'VACATION').rate, leave.average_daily_salary,
            places=2)

    def test_a_vacation_entered_by_hand_is_left_to_the_payslip(self):
        leave = self._leave(self.vacation_type, date(2025, 7, 14), date(2025, 7, 20))
        leave.average_daily_salary = 1000.0
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        vacation = self.env['hr.accrual.type'].search([('code', '=', 'VACATION')])
        self.env['hr.payslip.accrual'].create({
            'payslip_id': slip.id, 'accrual_type_id': vacation.id,
            'quantity': 1, 'rate': 5000, 'amount': 5000,
        })
        slip.action_compute_sheet()
        self.assertEqual(self._of_type(slip, 'VACATION').mapped('amount'), [5000])

    def test_a_sickness_is_paid_by_the_employer_and_the_fund(self):
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 14), 'date_to': date(2025, 7, 20),
            'sick_leave_type': 'illness',
            'insurance_experience_years': 10,
            'average_daily_salary': 500.0,
        })
        sick.action_confirm()
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        employer = self._of_type(slip, 'SICK_EMP')
        fund = self._of_type(slip, 'SICK_FSS')
        self.assertEqual((employer.quantity, fund.quantity), (5, 2))
        self.assertAlmostEqual(employer.amount, 2500.0, places=2)
        self.assertAlmostEqual(fund.amount, 1000.0, places=2)
        # Both parts of the benefit are in the contribution base, whoever
        # finances them.
        self.assertTrue(employer.is_esv_base and fund.is_esv_base)
        self.assertTrue(self.env.ref(
            'l10n_ua_hr_salary.accrual_type_maternity').is_esv_base)

    def test_a_sick_time_off_without_a_certificate_stops_the_payslip(self):
        self._leave(self.sick_type, date(2025, 7, 14), date(2025, 7, 16))
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        with self.assertRaises(UserError):
            slip.action_compute_sheet()

    def _july_with_one_holiday(self):
        """July 2025 with one public holiday, on Wednesday 16th, and no
        production calendar: 23 weekdays in the norm."""
        self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', '2025-07-31 23:59:59'),
            ('date_to', '>=', '2025-07-01 00:00:00'),
        ]).unlink()
        if 'hr.production.calendar' in self.env:
            self.env['hr.production.calendar'].search([
                ('year', '=', 2025), ('company_id', '=', self.company.id),
            ]).unlink()
        self.env['resource.calendar.leaves'].create({
            'name': 'Holiday (absence pay test)',
            'date_from': '2025-07-16 00:00:00',
            'date_to': '2025-07-16 23:59:59',
        })

    def test_without_a_timesheet_the_days_away_are_not_paid_as_worked(self):
        # 14-20 July: five weekdays away, one of them a public holiday the
        # vacation does not include. The salary pays the other 18 weekdays
        # and the holiday, the vacation pay its 6 days — not both for any.
        self._july_with_one_holiday()
        self.version.wage = 23000
        leave = self._leave(self.vacation_type, date(2025, 7, 14), date(2025, 7, 20))
        leave.average_daily_salary = 1000.0
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertEqual((slip.scheduled_days, slip.worked_days), (23, 19))
        self.assertAlmostEqual(self._of_type(slip, 'SALARY').amount,
                               round(23000 * 19 / 23, 2), places=2)
        vacation = self._of_type(slip, 'VACATION')
        self.assertEqual(vacation.quantity, 6)
        self.assertAlmostEqual(vacation.amount, 6000.0, places=2)

    def test_a_salary_entered_by_hand_leaves_the_absences_to_it(self):
        leave = self._leave(self.vacation_type, date(2025, 7, 14), date(2025, 7, 20))
        leave.average_daily_salary = 1000.0
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        salary = self.env['hr.accrual.type'].search([('code', '=', 'SALARY')], limit=1)
        self.env['hr.payslip.accrual'].create({
            'payslip_id': slip.id, 'accrual_type_id': salary.id,
            'quantity': 1, 'rate': 25000, 'amount': 25000,
        })
        slip.action_compute_sheet()
        self.assertFalse(self._of_type(slip, 'VACATION'))

    def test_a_paid_time_off_without_a_ukrainian_category_stops_the_payslip(self):
        other = self.env['hr.leave.type'].create({
            'name': 'Paid Time Off (no category)', 'is_paid': True,
            'requires_allocation': False, 'company_id': self.company.id,
        })
        self._leave(other, date(2025, 7, 14), date(2025, 7, 16))
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        with self.assertRaises(UserError):
            slip.action_compute_sheet()

    def test_a_timesheet_that_has_the_vacation_as_worked_stops_the_payslip(self):
        if 'hr.timesheet.line' not in self.env:
            self.skipTest('l10n_ua_hr_attendance_sheet is not installed')
        self._july_with_one_holiday()
        leave = self._leave(self.vacation_type, date(2025, 7, 14), date(2025, 7, 15))
        leave.average_daily_salary = 1000.0
        work = self.env['hr.timesheet.code'].search([('is_worked', '=', True)], limit=1)
        sheet = self.env['hr.timesheet'].create({
            'month': '7', 'year': 2025, 'company_id': self.company.id})
        line = self.env['hr.timesheet.line'].create({
            'timesheet_id': sheet.id, 'employee_id': self.employee.id})
        self.env['hr.timesheet.day'].create([{
            'line_id': line.id, 'date': date(2025, 7, day), 'day_number': day,
            'code_id': work.id, 'hours': 8.0, 'is_scheduled': True,
        } for day in (14, 15)])
        sheet.state = 'confirmed'
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        with self.assertRaises(UserError):
            slip.action_compute_sheet()
