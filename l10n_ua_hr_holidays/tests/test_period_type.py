from datetime import date

from odoo.tests.common import TransactionCase


class TestPeriodType(TransactionCase):
    """PR 1: period_type on hr.leave.type + _get_work_year_for_date on hr.employee."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Employee = cls.env['hr.employee']
        cls.LeaveType = cls.env['hr.leave.type']

    def test_period_type_default_is_calendar(self):
        leave_type = self.LeaveType.create({'name': 'Ad-hoc leave'})
        self.assertEqual(leave_type.period_type, 'calendar')

    def test_period_type_explicit_work(self):
        leave_type = self.LeaveType.create({
            'name': 'Work-year leave',
            'period_type': 'work',
        })
        self.assertEqual(leave_type.period_type, 'work')

    def test_seeded_annual_types_use_work_period(self):
        """Data file + post-migration must mark annual types as work-year."""
        for xmlid in (
            'l10n_ua_hr_holidays.leave_type_annual_basic',
            'l10n_ua_hr_holidays.leave_type_annual_additional',
            'l10n_ua_hr_holidays.leave_type_additional_hazard',
            'l10n_ua_hr_holidays.leave_type_additional_irregular',
            'l10n_ua_hr_holidays.leave_type_additional_special_work',
        ):
            lt = self.env.ref(xmlid)
            self.assertEqual(
                lt.period_type, 'work',
                f'{xmlid} must use work-year accounting')

    def test_seeded_social_types_use_calendar_period(self):
        for xmlid in (
            'l10n_ua_hr_holidays.leave_type_social_children',
            'l10n_ua_hr_holidays.leave_type_chornobyl',
            'l10n_ua_hr_holidays.leave_type_veteran',
            'l10n_ua_hr_holidays.leave_type_educational',
            'l10n_ua_hr_holidays.leave_type_maternity',
            'l10n_ua_hr_holidays.leave_type_sick',
        ):
            lt = self.env.ref(xmlid)
            self.assertEqual(
                lt.period_type, 'calendar',
                f'{xmlid} must use calendar-year accounting')

    def test_work_year_first_period(self):
        emp = self.Employee.create({
            'name': 'Petro Pavlenko',
            'hire_date': date(2024, 7, 15),
        })
        start, end, idx = emp._get_work_year_for_date(date(2024, 9, 1))
        self.assertEqual(start, date(2024, 7, 15))
        self.assertEqual(end, date(2025, 7, 14))
        self.assertEqual(idx, 1)

    def test_work_year_second_period_after_anniversary(self):
        emp = self.Employee.create({
            'name': 'Iryna Koval',
            'hire_date': date(2024, 7, 15),
        })
        start, end, idx = emp._get_work_year_for_date(date(2025, 7, 15))
        self.assertEqual(start, date(2025, 7, 15))
        self.assertEqual(end, date(2026, 7, 14))
        self.assertEqual(idx, 2)

    def test_work_year_third_period(self):
        emp = self.Employee.create({
            'name': 'Oleh Bondar',
            'hire_date': date(2020, 3, 1),
        })
        start, end, idx = emp._get_work_year_for_date(date(2023, 6, 10))
        self.assertEqual(start, date(2023, 3, 1))
        self.assertEqual(end, date(2024, 2, 29))  # leap year boundary
        self.assertEqual(idx, 4)

    def test_work_year_without_hire_date_returns_empty(self):
        emp = self.Employee.create({'name': 'No hire date'})
        start, end, idx = emp._get_work_year_for_date(date(2025, 1, 1))
        self.assertFalse(start)
        self.assertFalse(end)
        self.assertEqual(idx, 0)

    def test_work_year_before_hire_returns_empty(self):
        emp = self.Employee.create({
            'name': 'Future hire',
            'hire_date': date(2025, 6, 1),
        })
        start, end, idx = emp._get_work_year_for_date(date(2025, 3, 1))
        self.assertFalse(start)
        self.assertFalse(end)
        self.assertEqual(idx, 0)

