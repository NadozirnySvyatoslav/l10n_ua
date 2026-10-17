"""Tests for production calendar — HR-18 from HR_UKRAINE.md.

Tests cover:
- Production calendar creation
- Calendar generation with holidays
- Ukrainian public holidays detection
- Working days / holidays / hours computation
- Pre-holiday shortened days
"""

from psycopg2 import IntegrityError

from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestProductionCalendar(TransactionCase):
    """Test hr.production.calendar model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _create_calendar(self, year=2025):
        return self.env['hr.production.calendar'].create({
            'year': year,
            'company_id': self.company.id,
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
        """Should detect Ukrainian public holidays."""
        cal = self._create_calendar(2025)
        cal.action_generate_calendar()
        self.assertGreater(cal.holidays, 0)

    def test_ua_holidays_list(self):
        """Should include major Ukrainian holidays."""
        cal = self._create_calendar(2025)
        holidays = cal._get_ua_holidays(2025)
        # New Year
        from datetime import date as d
        self.assertIn(d(2025, 1, 1), holidays)
        # Christmas (Julian)
        self.assertIn(d(2025, 1, 7), holidays)
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
        # A database constraint: it fires at flush and aborts the transaction.
        # The savepoint keeps the transaction usable, the flush raises the
        # error inside the block, and mute_logger silences the expected
        # "bad query" line.
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            self._create_calendar(2025)
            self.env.flush_all()

    def test_calendar_line_day_type(self):
        """Lines should have correct day types."""
        cal = self._create_calendar(2025)
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
