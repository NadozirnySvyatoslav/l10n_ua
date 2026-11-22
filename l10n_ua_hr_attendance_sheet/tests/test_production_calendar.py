"""Tests for production calendar — HR-18 from HR_UKRAINE.md.

Tests cover:
- Production calendar creation
- Calendar generation with holidays
- Ukrainian public holidays detection
- Working days / holidays / hours computation
- Pre-holiday shortened days
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductionCalendar(TransactionCase):
    """Test hr.production.calendar model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _create_calendar(self, year=2025, **kwargs):
        return self.env['hr.production.calendar'].create({
            'year': year,
            'company_id': self.company.id,
            **kwargs,
        })

    def test_calendar_creation(self):
        """Calendar should be created with computed name."""
        cal = self._create_calendar(2025)
        self.assertIn('2025', cal.name)

    def test_calendar_generate(self):
        """Generate should create 365 lines for non-leap year."""
        cal = self._create_calendar(2025)
        cal.action_generate_calendar()
        self.assertEqual(cal.total_days, 365)

    def test_calendar_generate_leap_year(self):
        """Generate should create 366 lines for leap year."""
        cal = self._create_calendar(2024)
        cal.action_generate_calendar()
        self.assertEqual(cal.total_days, 366)

    def test_calendar_working_days(self):
        """Working days should be less than total days."""
        cal = self._create_calendar(2025)
        cal.action_generate_calendar()
        self.assertGreater(cal.working_days, 200)
        self.assertLess(cal.working_days, 270)

    def test_calendar_holidays(self):
        """Should detect Ukrainian public holidays (outside martial law)."""
        cal = self._create_calendar(2025, martial_law=False)
        cal.action_generate_calendar()
        self.assertGreater(cal.holidays, 0)

    def test_ua_holidays_list(self):
        """Should include major Ukrainian holidays."""
        cal = self._create_calendar(2025)
        holidays = cal._get_ua_holidays(2025)
        # New Year
        from datetime import date as d
        self.assertIn(d(2025, 1, 1), holidays)
        # Since 2023 there is no Julian Christmas
        self.assertNotIn(d(2025, 1, 7), holidays)
        # Independence Day
        self.assertIn(d(2025, 8, 24), holidays)
        # Constitution Day
        self.assertIn(d(2025, 6, 28), holidays)
        # Christmas (Gregorian)
        self.assertIn(d(2025, 12, 25), holidays)

    def test_calendar_working_hours(self):
        """Working hours should be approximately working_days * 8."""
        cal = self._create_calendar(2025)
        cal.action_generate_calendar()
        # Some days are shortened (7h), so total < working_days * 8
        self.assertGreater(cal.working_hours, 0)

    def test_calendar_unique_constraint(self):
        """Same year + company should fail."""
        self._create_calendar(2025)
        with self.assertRaises(Exception):
            self._create_calendar(2025)

    def test_calendar_line_day_type(self):
        """Lines should have correct day types."""
        cal = self._create_calendar(2025, martial_law=False)
        cal.action_generate_calendar()
        day_types = set(cal.line_ids.mapped('day_type'))
        self.assertIn('working', day_types)
        self.assertIn('weekend', day_types)
        self.assertIn('holiday', day_types)

    def test_calendar_line_month_computed(self):
        """Month should be computed from date."""
        cal = self._create_calendar(2025)
        cal.action_generate_calendar()
        jan_lines = cal.line_ids.filtered(lambda l: l.month == 1)
        self.assertEqual(len(jan_lines), 31)

    def test_ua_holidays_since_2023(self):
        """Law 3005-IX: Christmas only on 25.12, 8 May instead of 9 May,
        Defenders Day on 1 October instead of 14 October."""
        from datetime import date as d
        holidays = self._create_calendar(2026)._get_ua_holidays(2026)
        self.assertIn(d(2026, 12, 25), holidays)
        self.assertNotIn(d(2026, 1, 7), holidays)
        self.assertIn(d(2026, 5, 8), holidays)
        self.assertNotIn(d(2026, 5, 9), holidays)
        self.assertIn(d(2026, 10, 1), holidays)
        self.assertNotIn(d(2026, 10, 14), holidays)
        old = self._create_calendar(2021)._get_ua_holidays(2021)
        self.assertIn(d(2021, 1, 7), old)
        self.assertIn(d(2021, 5, 9), old)
        self.assertIn(d(2021, 10, 14), old)

    def test_martial_law_by_default_no_days_off(self):
        """Under martial law (the default) 2026 has no non-working holidays:
        every weekday is an 8-hour working day."""
        from datetime import date as d
        cal = self._create_calendar(2026)
        self.assertTrue(cal.martial_law)
        cal.action_generate_calendar()
        self.assertEqual(cal.holidays, 0)
        self.assertEqual(cal.working_days, 261)
        self.assertEqual(cal.working_hours, 261 * 8.0)
        independence = cal.line_ids.filtered(lambda l: l.date == d(2026, 8, 24))
        self.assertEqual(independence.day_type, 'working')
        self.assertTrue(independence.holiday_name)

    def test_without_martial_law_holidays_are_days_off(self):
        from datetime import date as d
        cal = self._create_calendar(2026, martial_law=False)
        cal.action_generate_calendar()
        defenders = cal.line_ids.filtered(lambda l: l.date == d(2026, 10, 1))
        self.assertEqual(defenders.day_type, 'holiday')
        # 30 September is the shortened pre-holiday day
        eve = cal.line_ids.filtered(lambda l: l.date == d(2026, 9, 30))
        self.assertEqual(eve.working_hours, 7.0)
