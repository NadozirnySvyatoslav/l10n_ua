"""A timesheet left as generated pays what the payslip pays without one.

The generator and the payslip read the working days, the hours of a day, the
version and the contract of a day and the public holidays by the same rules;
these tests hold them to it on July 2025: 23 weekdays, one public holiday on
Wednesday 16th, no production calendar unless a test keeps one.
"""
from datetime import date

from odoo.tests import tagged

from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestGeneratedTimesheet(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'hr.timesheet.line' not in cls.env or 'hr.sick.leave' not in cls.env:
            return
        cls.vacation_type = cls.env['hr.leave.type'].create({
            'name': 'Additional Leave (generated timesheet test)',
            'ua_leave_category': 'annual_additional', 'is_paid': True,
            'is_calendar_days': True, 'requires_allocation': False,
            'company_id': cls.company.id,
        })
        cls.version.write({'wage': 23000, 'tariff_grade_id': False})

    def setUp(self):
        super().setUp()
        if 'hr.timesheet.line' not in self.env or 'hr.sick.leave' not in self.env:
            self.skipTest('the attendance sheet or the holidays module is not installed')
        self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', '2025-07-31 23:59:59'),
            ('date_to', '>=', '2025-07-01 00:00:00'),
        ]).unlink()
        self.env['hr.production.calendar'].search([
            ('year', '=', 2025), ('company_id', '=', self.company.id),
        ]).unlink()
        self.env['resource.calendar.leaves'].create({
            'name': 'Holiday (generated timesheet test)',
            'date_from': '2025-07-16 00:00:00',
            'date_to': '2025-07-16 23:59:59',
        })

    def _generate(self):
        sheet = self.env['hr.timesheet'].create({
            'month': '7', 'year': 2025, 'company_id': self.company.id})
        line = self.env['hr.timesheet.line'].create({
            'timesheet_id': sheet.id, 'employee_id': self.employee.id})
        line.action_generate_days()
        return line

    def _day(self, line, day):
        return line.day_ids.filtered(lambda d: d.date == date(2025, 7, day))

    def _salary(self, slip):
        return sum(slip.accrual_ids.filtered(
            lambda a: a.accrual_type_id.code == 'SALARY').mapped('amount'))

    def _assert_parity(self, line):
        """The payslip without the sheet, then with it confirmed, counts the
        same days and hours and pays the same salary."""
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        slip.action_compute_sheet()
        without = (slip.worked_days, slip.worked_hours, self._salary(slip))
        self.assertEqual(line.worked_days, without[0])
        self.assertAlmostEqual(line.worked_hours, without[1], places=2)
        line.timesheet_id.state = 'confirmed'
        slip.action_compute_sheet()
        self.assertEqual(slip.worked_days, without[0])
        self.assertAlmostEqual(slip.worked_hours, without[1], places=2)
        self.assertAlmostEqual(self._salary(slip), without[2], places=2)

    def test_schedules_and_rates_give_the_payslip_hours(self):
        cases = [
            ('resource_calendar_ua_std40', 1.0, 8.0),
            ('resource_calendar_ua_std40', 0.5, 4.0),
            ('resource_calendar_ua_part20', 1.0, 4.0),
            ('resource_calendar_ua_part20', 0.5, 4.0),
            ('resource_calendar_ua_std36', 1.0, 7.2),
            ('resource_calendar_ua_shift2x2', 1.0, 8.0),
        ]
        for xmlid, rate, hours in cases:
            with self.subTest(schedule=xmlid, rate=rate):
                self.version.write({
                    'work_rate': rate,
                    'resource_calendar_id': self.env.ref(
                        'l10n_ua_hr_contract.%s' % xmlid).id,
                })
                line = self._generate()
                self.assertAlmostEqual(self._day(line, 1).hours, hours, places=2)
                self.assertAlmostEqual(self._day(line, 1).norm_hours, hours, places=2)
                self.assertEqual(self._day(line, 5).hours, 0.0)
                self._assert_parity(line)
                self.env['hr.payslip'].search([
                    ('employee_id', '=', self.employee.id)]).unlink()
                line.timesheet_id.unlink()

    def test_a_rate_changed_in_the_month_is_read_day_by_day(self):
        self.env['hr.version'].create({
            'employee_id': self.employee.id,
            'date_version': date(2025, 7, 15),
            'contract_date_start': self.version.contract_date_start,
            'wage': 23000, 'work_rate': 0.5,
            'contract_type_ua': 'permanent', 'employment_type_ua': 'primary',
            'company_id': self.company.id,
        })
        line = self._generate()
        self.assertEqual(self._day(line, 14).hours, 8.0)
        self.assertEqual(self._day(line, 15).hours, 4.0)
        # 10 weekdays at 8 hours, 13 at 4.
        self.assertAlmostEqual(line.worked_hours, 132.0, places=2)
        self._assert_parity(line)

    def test_a_rehire_in_the_month_keeps_the_days_of_the_first_contract(self):
        self.version.contract_date_end = date(2025, 7, 10)
        self.env['hr.version'].create({
            'employee_id': self.employee.id,
            'date_version': date(2025, 7, 21),
            'contract_date_start': date(2025, 7, 21),
            'wage': 23000,
            'contract_type_ua': 'permanent', 'employment_type_ua': 'primary',
            'company_id': self.company.id,
        })
        line = self._generate()
        self.assertEqual(self._day(line, 7).code_id.code, 'Я')
        self.assertEqual(self._day(line, 15).hours, 0.0)
        self.assertEqual(self._day(line, 21).code_id.code, 'Я')
        # 8 weekdays of the first contract, 9 of the second.
        self.assertEqual(line.worked_days, 17)
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 1), 'date_to': date(2025, 7, 31),
        })
        slip.action_compute_sheet()
        self.assertEqual(slip.worked_days, line.worked_days)
        self.assertAlmostEqual(slip.worked_hours, line.worked_hours, places=2)

    def test_a_holiday_inside_a_vacation_without_a_calendar_is_a_working_day(self):
        # No calendar marks the holiday as a day off: the vacation does not
        # include it, and it is worked and paid by the salary.
        self._vacation()
        line = self._generate()
        self.assertEqual(self._day(line, 15).code_id.code, 'ВД')
        self.assertEqual(self._day(line, 16).code_id.code, 'Я')
        self.assertEqual(self._day(line, 16).hours, 8.0)
        self.assertEqual(line.worked_days, 19)
        self._assert_parity(line)

    def test_a_holiday_inside_a_vacation_with_a_calendar_is_a_holiday(self):
        self.env['hr.production.calendar'].create({
            'year': 2025, 'company_id': self.company.id,
            'line_ids': [(0, 0, {
                'date': date(2025, 7, 16), 'day_type': 'holiday',
                'working_hours': 0.0,
            })],
        })
        self._vacation()
        line = self._generate()
        self.assertEqual(self._day(line, 16).code_id.code, 'СВ')
        self.assertEqual(self._day(line, 16).hours, 0.0)
        self.assertEqual(line.worked_days, 18)
        self._assert_parity(line)

    def test_a_vacation_starting_on_the_last_day_is_marked_on_it(self):
        # Thursday 31 July to Monday 4 August: the request starts on the last
        # day of the month, its moment in UTC after the midnight of that day.
        self._vacation(date(2025, 7, 31), date(2025, 8, 4))
        line = self._generate()
        self.assertEqual(self._day(line, 30).code_id.code, 'Я')
        self.assertEqual(self._day(line, 31).code_id.code, 'ВД')
        self.assertEqual(self._day(line, 31).hours, 0.0)
        self._assert_parity(line)

    def test_a_time_off_in_hours_leaves_the_day_worked(self):
        # Neither the generator nor the payslip takes the day of a time off
        # counted in hours or half days off the worked days.
        for unit in ('hour', 'half_day'):
            with self.subTest(unit=unit):
                leave_type = self.env['hr.leave.type'].create({
                    'name': 'Time off in %s (generated timesheet test)' % unit,
                    'request_unit': unit, 'requires_allocation': False,
                    'company_id': self.company.id,
                })
                leave = self.env['hr.leave'].create({
                    'name': 'Two hours off',
                    'employee_id': self.employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': date(2025, 7, 22),
                    'request_date_to': date(2025, 7, 22),
                })
                leave._action_validate()
                line = self._generate()
                self.assertEqual(self._day(line, 22).code_id.code, 'Я')
                self.assertEqual(self._day(line, 22).hours, 8.0)
                self._assert_parity(line)
                self.env['hr.payslip'].search([
                    ('employee_id', '=', self.employee.id)]).unlink()
                line.timesheet_id.unlink()
                leave.action_refuse()

    def test_a_certificate_in_draft_is_worked_and_a_confirmed_one_is_not(self):
        sick = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'date_from': date(2025, 7, 21), 'date_to': date(2025, 7, 25),
            'sick_leave_type': 'illness',
            'insurance_experience_years': 10,
            'average_daily_salary': 500.0,
        })
        line = self._generate()
        self.assertEqual(self._day(line, 21).code_id.code, 'Я')
        self._assert_parity(line)
        sick.action_confirm()
        line.action_generate_days()
        self.assertEqual(self._day(line, 21).code_id.code, 'ТН')

    def _vacation(self, day_from=date(2025, 7, 14), day_to=date(2025, 7, 20)):
        leave = self.env['hr.leave'].create({
            'name': 'Vacation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.vacation_type.id,
            'request_date_from': day_from,
            'request_date_to': day_to,
        })
        leave._action_validate()
        leave.average_daily_salary = 1000.0
        return leave
