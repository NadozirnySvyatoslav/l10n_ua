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
        sick.confirmed_date = date(2025, 7, 21)
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

    def _sickness(self, day_from, day_to, **values):
        return self.env['hr.sick.leave'].create(dict({
            'employee_id': self.employee.id,
            'date_from': day_from, 'date_to': day_to,
            'sick_leave_type': 'illness',
            'insurance_experience_years': 10,
            'average_daily_salary': 500.0,
        }, **values))

    def test_a_sickness_without_a_certificate_leaves_its_days_unpaid(self):
        # The certificate has not come yet: the days are away and the payslip
        # is computed all the same, with nothing paid for them.
        self._july_with_one_holiday()
        self.version.wage = 23000
        self._leave(self.sick_type, date(2025, 7, 21), date(2025, 7, 25))
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertEqual(slip.worked_days, 18)
        self.assertFalse(self._of_type(slip, 'SICK_EMP') | self._of_type(slip, 'SICK_FSS'))

    def test_a_certificate_in_draft_leaves_its_days_worked(self):
        # Not confirmed yet, the certificate is nobody's word: its days are
        # worked, as the timesheet generator has them, until it is.
        self._july_with_one_holiday()
        self.version.wage = 23000
        self._sickness(date(2025, 7, 21), date(2025, 7, 25))
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertEqual(slip.worked_days, 23)
        self.assertAlmostEqual(self._of_type(slip, 'SALARY').amount, 23000.0, places=2)

    def test_a_certificate_confirmed_next_month_is_paid_there_for_all_its_days(self):
        # Sick from 28 July to 3 August; the certificate is confirmed on
        # 5 August. July pays nothing for the sickness, August pays all 7
        # days: 5 by the employer, 2 by the fund.
        sick = self._sickness(date(2025, 7, 28), date(2025, 8, 3))
        july = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        sick.action_confirm()
        sick.confirmed_date = date(2025, 8, 5)
        august = self._payslip(date(2025, 8, 1), date(2025, 8, 31))
        self.assertFalse(self._of_type(july, 'SICK_EMP') | self._of_type(july, 'SICK_FSS'))
        employer = self._of_type(august, 'SICK_EMP')
        self.assertEqual(sum(employer.mapped('quantity')), 5)
        self.assertEqual(sum(self._of_type(august, 'SICK_FSS').mapped('quantity')), 2)
        # A line per month: the 4 days of July carry their month.
        july_days = employer.filtered(lambda a: a.period_month == date(2025, 7, 1))
        self.assertEqual(july_days.quantity, 4)
        self.assertAlmostEqual(
            sum((self._of_type(august, 'SICK_EMP')
                 | self._of_type(august, 'SICK_FSS')).mapped('amount')),
            3500.0, places=2)

    def test_a_certificate_paid_before_the_update_is_not_paid_again(self):
        # Paid outside the payslip before benefits were accrued in it: it
        # carries no confirmation date and is left alone.
        sick = self._sickness(date(2025, 7, 14), date(2025, 7, 20))
        sick.state = 'paid'
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertFalse(self._of_type(slip, 'SICK_EMP') | self._of_type(slip, 'SICK_FSS'))

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

    def test_a_paid_time_off_without_a_ukrainian_category_is_paid_as_a_vacation(self):
        # As the time off itself calculates its pay: at the average daily
        # salary, without stopping the payslip.
        self._july_with_one_holiday()
        other = self.env['hr.leave.type'].create({
            'name': 'Paid Time Off (no category)', 'is_paid': True,
            'requires_allocation': False, 'company_id': self.company.id,
        })
        leave = self._leave(other, date(2025, 7, 21), date(2025, 7, 23))
        leave.average_daily_salary = 1000.0
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        vacation = self._of_type(slip, 'VACATION')
        self.assertEqual(vacation.quantity, 3)
        self.assertAlmostEqual(vacation.amount, 3000.0, places=2)

    def test_a_holiday_is_read_on_its_day_in_the_company_time_zone(self):
        # Entered in Kyiv time, a holiday on 23 July starts on 22 July at
        # 21:00 UTC; a holiday of another company does not count.
        self._july_with_one_holiday()
        self.company.resource_calendar_id.tz = 'Europe/Kyiv'
        Holiday = self.env['resource.calendar.leaves']
        Holiday.create({
            'name': 'Local holiday',
            'date_from': '2025-07-22 21:00:00', 'date_to': '2025-07-23 20:59:59',
        })
        other = self.env['res.company'].create({'name': 'Holiday Test Other Company'})
        Holiday.with_company(other).create({
            'name': 'Holiday of another company',
            'date_from': '2025-07-24 00:00:00', 'date_to': '2025-07-24 23:59:59',
        })
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        self.assertEqual(slip._public_holiday_dates(),
                         {date(2025, 7, 16), date(2025, 7, 23)})

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

    def test_without_a_timesheet_a_hire_mid_month_is_paid_for_the_days_after_it(self):
        # Hired on Thursday 17 July: 11 of the 23 weekdays of the month are
        # under contract, as the timesheet generator would mark them.
        self._july_with_one_holiday()
        self.version.write({
            'wage': 23000,
            'contract_date_start': date(2025, 7, 17),
            'date_version': date(2025, 7, 17),
        })
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertEqual((slip.scheduled_days, slip.worked_days), (23, 11))
        self.assertAlmostEqual(self._of_type(slip, 'SALARY').amount,
                               round(23000 * 11 / 23, 2), places=2)

    # --- closed months, retro recalculation, minimum contribution ---

    def _closed(self, month_from, month_to):
        slip = self._payslip(month_from, month_to)
        slip.state = 'done'
        return slip

    def test_sick_days_paid_by_a_closed_month_are_taken_back(self):
        # July is closed paying 28-31 July by the salary; the certificate for
        # 28 July - 3 August is confirmed on 5 August. August pays the
        # benefit for all 7 days and takes back the salary of the 4 weekdays
        # of July: 32 of its 184 hours.
        self.version.wage = 23000
        july = self._closed(date(2025, 7, 1), date(2025, 7, 31))
        sick = self._sickness(date(2025, 7, 28), date(2025, 8, 3))
        sick.action_confirm()
        sick.confirmed_date = date(2025, 8, 5)
        august = self._payslip(date(2025, 8, 1), date(2025, 8, 31))
        retro = self._of_type(august, 'RETRO')
        self.assertAlmostEqual(retro.amount, -round(23000 * 32 / 184, 2), places=2)
        self.assertEqual(
            self.env['hr.payslip.retro'].search([('target_payslip_id', '=', august.id)])
            .source_payslip_id, july)

    def test_a_month_closed_before_the_hours_method_is_left_to_the_accountant(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('l10n_ua_hr_salary.hours_method_date', '2025-08-01')
        # The parameter is cached: clear it before the test's rollback.
        self.addCleanup(params.set_param, 'l10n_ua_hr_salary.hours_method_date', False)
        july = self._closed(date(2025, 7, 1), date(2025, 7, 31))
        sick = self._sickness(date(2025, 7, 28), date(2025, 8, 3))
        sick.action_confirm()
        sick.confirmed_date = date(2025, 8, 5)
        august = self._payslip(date(2025, 8, 1), date(2025, 8, 31))
        self.assertFalse(self._of_type(august, 'RETRO'))
        self.assertTrue(august.message_ids.filtered(lambda m: july.name in (m.body or '')))
        with self.assertRaises(UserError):
            july.action_retro_recalculate()

    def test_retro_of_an_unchanged_month_finds_no_difference(self):
        self._closed(date(2025, 7, 1), date(2025, 7, 31))
        july = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee.id), ('state', '=', 'done')])
        august = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 8, 1), 'date_to': date(2025, 8, 31),
        })
        july.action_retro_recalculate()
        self.assertFalse(self._of_type(august, 'RETRO'))

    def test_a_part_time_schedule_and_rate_reduce_once(self):
        # Both the 20-hour schedule and the 0.5 rate say the same half time.
        self._july_with_one_holiday()
        self.version.write({
            'wage': 23000, 'work_rate': 0.5,
            'resource_calendar_id': self.env.ref(
                'l10n_ua_hr_contract.resource_calendar_ua_part20').id,
        })
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertAlmostEqual(self._of_type(slip, 'SALARY').amount, 11500.0, places=2)

    def test_the_minimum_contribution_skips_a_hire_in_the_middle_of_the_month(self):
        # Hired on 17 July for a salary below the minimum wage: the
        # contribution is charged on what was accrued.
        self._july_with_one_holiday()
        self.version.write({
            'wage': 7000,
            'contract_date_start': date(2025, 7, 17),
            'date_version': date(2025, 7, 17),
        })
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertAlmostEqual(slip.esv_base, round(7000 * 11 / 23, 2), places=2)

    def test_the_minimum_contribution_holds_for_a_month_under_contract(self):
        # Under contract all July with unpaid days off: raised to the minimum.
        self._july_with_one_holiday()
        unpaid = self.env['hr.leave.type'].create({
            'name': 'Unpaid (absence pay test)', 'ua_leave_category': 'unpaid',
            'is_paid': False, 'requires_allocation': False,
            'company_id': self.company.id,
        })
        self.version.wage = 7000
        self._leave(unpaid, date(2025, 7, 21), date(2025, 7, 25))
        slip = self._payslip(date(2025, 7, 1), date(2025, 7, 31))
        self.assertAlmostEqual(slip.esv_base, self.psp_params.min_wage, places=2)

    def test_the_minimum_contribution_holds_for_a_hire_on_the_first_working_day(self):
        # June 2025 starts on a Sunday: hired on Monday the 2nd and at work
        # every working day of the month, the base is raised to the minimum.
        self.version.write({
            'wage': 7000,
            'contract_date_start': date(2025, 6, 2),
            'date_version': date(2025, 6, 2),
        })
        slip = self._payslip(date(2025, 6, 1), date(2025, 6, 30))
        self.assertAlmostEqual(slip.esv_base, self.psp_params.min_wage, places=2)

    def test_the_contribution_ceiling_applies_to_each_month_of_a_benefit(self):
        # A salary above the ceiling, and a benefit confirmed in August for
        # days of July and August: July's part has the ceiling of July on its
        # own, August's part shares August's ceiling with the salary.
        ceiling = self.psp_params.max_esv_base
        self.version.wage = ceiling * 3
        sick = self._sickness(date(2025, 7, 28), date(2025, 8, 3),
                              average_daily_salary=10000.0)
        sick.action_confirm()
        sick.confirmed_date = date(2025, 8, 5)
        august = self._payslip(date(2025, 8, 1), date(2025, 8, 31))
        self.assertAlmostEqual(august.esv_base, ceiling + 4 * 10000.0, places=2)
