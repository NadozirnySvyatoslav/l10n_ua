"""Tests for version allowances — HR-5 from HR_UKRAINE.md.

Tests cover:
- Allowance type creation and reference data
- Allowance calculation methods (fixed, percent_salary, percent_min_wage)
- Active status based on dates
- Allowance totals on version
"""

from datetime import date
from psycopg2 import IntegrityError
from odoo.tests import tagged
from odoo.tools import mute_logger
from .common import ContractTestCase


@tagged('post_install', '-at_install')
class TestAllowanceType(ContractTestCase):
    """Test hr.allowance.type reference data."""

    def test_allowance_type_creation(self):
        """Allowance type should have required fields."""
        self.assertTrue(self.allowance_seniority.name)
        self.assertTrue(self.allowance_seniority.code)
        self.assertEqual(self.allowance_seniority.category, 'seniority')

    def test_allowance_type_taxable_flags(self):
        """Tax flags should be set correctly."""
        self.assertTrue(self.allowance_seniority.is_taxable)
        self.assertTrue(self.allowance_seniority.is_esv_base)

    def test_allowance_type_unique_code(self):
        """Code should be unique."""
        # unique(code) is a database constraint: it fires at flush and aborts
        # the transaction. Wrap the failing insert in a savepoint (so the
        # transaction stays usable afterwards) and flush inside the block so
        # the IntegrityError is raised where assertRaises can catch it.
        # mute_logger silences the expected "bad query" error line.
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            self.env['hr.allowance.type'].create({
                'name': 'Duplicate',
                'code': 'TEST_SENIORITY',
                'category': 'other',
            })
            self.env.flush_all()



@tagged('post_install', '-at_install')
class TestVersionAllowance(ContractTestCase):
    """Test hr.version.allowance calculations."""

    def _create_allowance(self, version=None, **kwargs):
        if version is None:
            version = self._create_version(wage=25000)
        vals = {
            'version_id': version.id,
            'allowance_type_id': self.allowance_seniority.id,
            'calculation_method': 'fixed',
            'amount': 5000,
        }
        vals.update(kwargs)
        return self.env['hr.version.allowance'].create(vals)

    def test_fixed_allowance_amount(self):
        """Fixed allowance should use the direct amount."""
        allowance = self._create_allowance(calculation_method='fixed', amount=5000)
        self.assertEqual(allowance.calculated_amount, 5000)

    def test_percent_salary_allowance(self):
        """Percent of salary: wage * percent / 100."""
        version = self._create_version(wage=30000)
        allowance = self._create_allowance(
            version=version,
            calculation_method='percent_salary',
            percent=10,
        )
        self.assertAlmostEqual(allowance.calculated_amount, 3000, places=2)

    def test_allowance_active_no_dates(self):
        """Allowance without dates should be active."""
        allowance = self._create_allowance()
        self.assertTrue(allowance.is_active)

    def test_allowance_active_within_dates(self):
        """Allowance within date range should be active."""
        allowance = self._create_allowance(
            date_from=date(2024, 1, 1),
            date_to=date(2027, 12, 31),
        )
        self.assertTrue(allowance.is_active)

    def test_allowance_inactive_past(self):
        """Allowance with past end date should be inactive."""
        allowance = self._create_allowance(
            date_from=date(2020, 1, 1),
            date_to=date(2020, 12, 31),
        )
        self.assertFalse(allowance.is_active)

    def test_multiple_allowances_total(self):
        """Version total_allowances should sum active allowances."""
        version = self._create_version(wage=25000)
        self._create_allowance(version=version, amount=3000)
        self._create_allowance(
            version=version,
            allowance_type_id=self.allowance_hazard.id,
            amount=4000,
        )
        version.invalidate_recordset()
        self.assertEqual(version.total_allowances, 7000)
        self.assertEqual(version.total_wage, 32000)

    def test_allowance_active_between_uses_the_period(self):
        """An allowance is judged by the period asked about, not by today."""
        version = self._create_version(wage=25000)
        past = self._create_allowance(
            version=version, date_from=date(2020, 1, 1), date_to=date(2020, 12, 31))
        later = self._create_allowance(
            version=version, allowance_type_id=self.allowance_hazard.id,
            date_from=date(2021, 1, 1))
        allowances = past | later
        self.assertEqual(
            allowances._l10n_ua_active_between(date(2020, 6, 1), date(2020, 6, 30)),
            past)
        self.assertEqual(
            allowances._l10n_ua_active_between(date(2020, 12, 1), date(2021, 1, 31)),
            allowances)
