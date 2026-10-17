"""The working days, public holidays, version and contract of a day, as the
timesheet generator and the payslip both read them."""
from datetime import date

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestWorkTimeHelpers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Work Time Helpers Employee',
            'company_id': cls.company.id,
        })
        # The version Odoo creates with the card, turned into a contract
        # from the start of 2025.
        cls.first = cls.employee.version_ids[:1]
        cls.first.write({
            'date_version': date(2025, 1, 1),
            'contract_date_start': date(2025, 1, 1),
        })

    def test_the_working_days_are_the_weekdays_at_the_company_day(self):
        self.company.resource_calendar_id.hours_per_day = 7.0
        working = self.company._l10n_ua_working_dates(date(2025, 7, 1), date(2025, 7, 31))
        self.assertEqual(len(working), 23)
        self.assertEqual(working[date(2025, 7, 1)], 7.0)
        self.assertNotIn(date(2025, 7, 5), working)

    def test_a_company_without_a_schedule_works_eight_hours(self):
        company = self.env['res.company'].create({'name': 'Work Time Helpers Company'})
        company.resource_calendar_id = False
        working = company._l10n_ua_working_dates(date(2025, 7, 1), date(2025, 7, 1))
        self.assertEqual(working, {date(2025, 7, 1): 8.0})

    def test_the_public_holidays_are_those_of_the_company_and_of_none(self):
        Holiday = self.env['resource.calendar.leaves']
        Holiday.search([
            ('resource_id', '=', False),
            ('date_from', '<=', '2025-07-31 23:59:59'),
            ('date_to', '>=', '2025-07-01 00:00:00'),
        ]).unlink()
        self.company.resource_calendar_id.tz = 'UTC'
        Holiday.create({
            'name': 'Holiday of no company',
            'date_from': '2025-07-16 00:00:00', 'date_to': '2025-07-16 23:59:59',
        })
        other = self.env['res.company'].create({'name': 'Work Time Helpers Other'})
        Holiday.with_company(other).create({
            'name': 'Holiday of another company',
            'date_from': '2025-07-17 00:00:00', 'date_to': '2025-07-17 23:59:59',
        })
        self.assertEqual(
            self.company._l10n_ua_public_holiday_dates(date(2025, 7, 1), date(2025, 7, 31)),
            {date(2025, 7, 16)})

    def test_a_version_without_a_contract_is_passed_over(self):
        # Dated later, but carrying no contract period: Odoo's own choice of
        # the version of a day would take it, the rule of the payslip not.
        loose = self.env['hr.version'].create({
            'employee_id': self.employee.id,
            'date_version': date(2025, 6, 1),
        })
        self.assertEqual(self.employee._get_version(date(2025, 7, 1)), loose)
        self.assertEqual(self.employee._l10n_ua_version_on(date(2025, 7, 1)), self.first)
        self.assertFalse(self.employee._l10n_ua_version_on(date(2024, 12, 31)))

    def test_a_day_between_two_contracts_is_not_under_contract(self):
        self.first.contract_date_end = date(2025, 7, 10)
        self.env['hr.version'].create({
            'employee_id': self.employee.id,
            'date_version': date(2025, 7, 21),
            'contract_date_start': date(2025, 7, 21),
        })
        employed = self.employee._l10n_ua_employed_on
        self.assertFalse(employed(date(2024, 12, 31)))
        self.assertTrue(employed(date(2025, 7, 10)))
        self.assertFalse(employed(date(2025, 7, 15)))
        self.assertTrue(employed(date(2025, 7, 21)))

    def test_an_officer_reads_the_contract_of_a_day(self):
        # The contract dates are for HR managers; a timesheet officer is not
        # one, and asks about the days all the same.
        officer = new_test_user(
            self.env, login='work_time_helpers_officer',
            groups='l10n_ua_hr_base.group_hr_ua_officer')
        employee = self.employee.with_user(officer)
        self.assertTrue(employee._l10n_ua_employed_on(date(2025, 7, 1)))
        self.assertEqual(employee._l10n_ua_version_on(date(2025, 7, 1)), self.first)
