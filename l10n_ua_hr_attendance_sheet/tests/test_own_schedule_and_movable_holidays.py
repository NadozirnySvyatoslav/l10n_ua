"""Norm by the employee's own schedule and movable holidays (#631)."""
from datetime import date

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_hr_attendance_sheet.models.hr_production_calendar import (
    orthodox_easter,
)


@tagged('post_install', '-at_install')
class TestMovableHolidays(TransactionCase):

    def test_orthodox_easter_computus(self):
        known = {
            2021: date(2021, 5, 2), 2022: date(2022, 4, 24),
            2023: date(2023, 4, 16), 2024: date(2024, 5, 5),
            2025: date(2025, 4, 20), 2026: date(2026, 4, 12),
            2027: date(2027, 5, 2), 2030: date(2030, 4, 28),
        }
        for year, easter in known.items():
            self.assertEqual(orthodox_easter(year), easter, year)

    def test_easter_and_trinity_in_holiday_list(self):
        holidays = self.env['hr.production.calendar']._get_ua_holidays(2026)
        self.assertIn(date(2026, 4, 12), holidays)
        self.assertIn(date(2026, 5, 31), holidays)

    def _generate(self, year, **vals):
        cal = self.env['hr.production.calendar'].create({
            'year': year, 'company_id': self.env.company.id, **vals})
        cal.action_generate_calendar()
        return {line.date: line for line in cal.line_ids}

    def test_sunday_holiday_moves_day_off_to_monday(self):
        """Without martial law Easter (12.04.2026) and Trinity (31.05.2026)
        fall on Sundays: the following Mondays are days off (art. 67)."""
        lines = self._generate(2026, martial_law=False)
        self.assertEqual(lines[date(2026, 4, 12)].day_type, 'holiday')
        for monday in (date(2026, 4, 13), date(2026, 6, 1)):
            self.assertEqual(lines[monday].day_type, 'transferred')
            self.assertFalse(lines[monday].is_working_day)
            self.assertEqual(lines[monday].working_hours, 0)
        # 28.06.2026 (Constitution Day) is a Sunday too.
        self.assertEqual(lines[date(2026, 6, 29)].day_type, 'transferred')

    def test_martial_law_keeps_movable_holidays_working(self):
        lines = self._generate(2026)
        for day in (date(2026, 4, 12), date(2026, 5, 31)):
            self.assertEqual(lines[day].day_type, 'weekend')
            self.assertTrue(lines[day].holiday_name)
        self.assertEqual(lines[date(2026, 4, 13)].day_type, 'working')
        self.assertEqual(lines[date(2026, 6, 1)].day_type, 'working')


@tagged('post_install', '-at_install')
class TestOwnScheduleNorm(TransactionCase):
    """June 2025: 21 weekdays, 25 days Monday to Saturday."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.department = cls.env['hr.department'].create({
            'name': 'Цех (власний графік)', 'company_id': cls.company.id,
        })
        cls.six_day = cls.env['resource.calendar'].create({
            'name': 'Шестиденка 40 год',
            'company_id': cls.company.id,
            'attendance_ids': [Command.clear()] + [
                Command.create({
                    'dayofweek': str(dow),
                    'duration_hours': 7.0 if dow < 5 else 5.0,
                    'hour_from': 0, 'hour_to': 0,
                }) for dow in range(6)
            ],
        })

    def _employee(self, name, calendar=None):
        employee = self.env['hr.employee'].create({
            'name': name,
            'company_id': self.company.id,
            'department_id': self.department.id,
        })
        vals = {
            'employee_id': employee.id,
            'contract_date_start': date(2024, 1, 1),
            'date_version': date(2024, 1, 1),
            'company_id': self.company.id,
            'department_id': self.department.id,
        }
        if calendar:
            vals['resource_calendar_id'] = calendar.id
        version = self.env['hr.version'].create(vals)
        employee.write({'current_version_id': version.id})
        return employee

    def _sheet(self, month=6, year=2025):
        sheet = self.env['hr.timesheet'].create({
            'year': year, 'month': str(month),
            'department_id': self.department.id,
            'company_id': self.company.id,
        })
        sheet.action_generate_lines()
        return {line.employee_id: line for line in sheet.line_ids}

    def test_six_day_employee_gets_own_norm(self):
        five = self._employee('П’ятиденка')
        six = self._employee('Шестиденка', self.six_day)
        lines = self._sheet()
        self.assertEqual(lines[five].scheduled_days, 21)
        self.assertEqual(lines[five].worked_days, 21)
        self.assertEqual(lines[six].scheduled_days, 25)
        self.assertEqual(lines[six].worked_days, 25)
        self.assertAlmostEqual(lines[six].worked_hours, 21 * 7.0 + 4 * 5.0)
        saturday = lines[six].day_ids.filtered(lambda d: d.date == date(2025, 6, 7))
        self.assertTrue(saturday.is_scheduled)
        self.assertEqual(saturday.hours, 5.0)
        sunday = lines[six].day_ids.filtered(lambda d: d.date == date(2025, 6, 8))
        self.assertFalse(sunday.is_scheduled)

    def test_own_schedule_respects_holidays_off(self):
        """Without martial law a holiday is a day off on the own schedule as
        well, and its eve is an hour shorter."""
        self.env['hr.production.calendar'].create({
            'year': 2026, 'company_id': self.company.id,
            'martial_law': False,
        }).action_generate_calendar()
        six = self._employee('Шестиденка у травні', self.six_day)
        line = self._sheet(month=5, year=2026)[six]
        days = {d.date: d for d in line.day_ids}
        # 01.05.2026 (Friday) and 08.05.2026 (Friday) are holidays.
        self.assertFalse(days[date(2026, 5, 1)].is_scheduled)
        self.assertFalse(days[date(2026, 5, 8)].is_scheduled)
        # Saturday is a working day of the own schedule ...
        self.assertTrue(days[date(2026, 5, 30)].is_scheduled)
        # ... and the eve of 08.05 is an hour shorter.
        self.assertEqual(days[date(2026, 5, 7)].hours, 6.0)
        # May 2026: 31 days, 5 Sundays, 2 holidays on working days.
        self.assertEqual(line.scheduled_days, 31 - 5 - 2)
