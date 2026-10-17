"""The days of a timesheet line: the working days of the production
calendar, and the norm kept next to the hours worked."""
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGenerateDays(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.resource_calendar_id.hours_per_day = 8.0
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Generate Days Employee',
            'company_id': cls.company.id,
        })
        cls.employee.version_ids[:1].write({
            'date_version': date(2024, 1, 1),
            'contract_date_start': date(2024, 1, 1),
            'work_rate': 1.0,
            'resource_calendar_id': cls.env.ref(
                'l10n_ua_hr_contract.resource_calendar_ua_std40').id,
        })
        cls.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', '2025-07-31 23:59:59'),
            ('date_to', '>=', '2025-07-01 00:00:00'),
        ]).unlink()
        cls.env['hr.production.calendar'].search([
            ('year', '=', 2025), ('company_id', '=', cls.company.id),
        ]).unlink()

    def _line(self):
        sheet = self.env['hr.timesheet'].create({
            'month': '7', 'year': 2025, 'company_id': self.company.id})
        return self.env['hr.timesheet.line'].create({
            'timesheet_id': sheet.id, 'employee_id': self.employee.id})

    def _day(self, line, day):
        return line.day_ids.filtered(lambda d: d.date == date(2025, 7, day))

    def test_without_a_calendar_the_weekdays_are_worked(self):
        line = self._line()
        line.action_generate_days()
        self.assertEqual(line.worked_days, 23)
        self.assertEqual(self._day(line, 5).code_id.code, 'В')

    def test_the_production_calendar_reads_a_day_by_its_type(self):
        self.env['hr.production.calendar'].create({
            'year': 2025, 'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'date': date(2025, 7, 15), 'day_type': 'working',
                        'working_hours': 7.0}),
                (0, 0, {'date': date(2025, 7, 16), 'day_type': 'holiday'}),
                (0, 0, {'date': date(2025, 7, 19), 'day_type': 'transferred',
                        'working_hours': 8.0}),
            ],
        })
        working = self.company._l10n_ua_working_dates(date(2025, 7, 14), date(2025, 7, 20))
        self.assertEqual(working, {
            date(2025, 7, 14): 8.0, date(2025, 7, 15): 7.0, date(2025, 7, 17): 8.0,
            date(2025, 7, 18): 8.0, date(2025, 7, 19): 8.0,
        })
        line = self._line()
        line.action_generate_days()
        self.assertEqual(self._day(line, 15).hours, 7.0)
        self.assertEqual(self._day(line, 16).code_id.code, 'СВ')
        self.assertEqual(self._day(line, 19).code_id.code, 'Я')

    def test_a_calendar_working_day_without_hours_is_a_full_day(self):
        # As the payslip reads it: the day is in the norm, so it is worked
        # for the full day of the company rather than for nothing.
        self.env['hr.production.calendar'].create({
            'year': 2025, 'company_id': self.company.id,
            'line_ids': [(0, 0, {'date': date(2025, 7, 15), 'day_type': 'working'})],
        })
        line = self._line()
        line.action_generate_days()
        self.assertEqual(self._day(line, 15).hours, 8.0)

    def test_the_norm_stays_when_the_hours_are_corrected(self):
        line = self._line()
        line.action_generate_days()
        day = self._day(line, 1)
        day.hours = 10.0
        self.assertEqual(day.norm_hours, 8.0)
        self.assertEqual(line.norm_hours, 184.0)
        self.assertEqual(line.overtime_diff, 2.0)
        # Overtime is entered by hand; the difference does not fill it.
        self.assertEqual(day.overtime_hours, 0.0)

    def test_hours_above_the_norm_are_shown_on_the_line(self):
        line = self._line()
        work = self.env['hr.timesheet.code'].search([('code', '=', 'Я')], limit=1)
        self.env['hr.timesheet.day'].create([{
            'line_id': line.id, 'date': date(2025, 7, day), 'day_number': day,
            'code_id': work.id, 'norm_hours': 8.0,
            'hours': 10.0 if day == 1 else 9.25,
        } for day in range(1, 20)])
        self.assertAlmostEqual(line.norm_hours, 152.0, places=2)
        self.assertAlmostEqual(line.worked_hours, 176.5, places=2)
        self.assertAlmostEqual(line.overtime_diff, 24.5, places=2)
