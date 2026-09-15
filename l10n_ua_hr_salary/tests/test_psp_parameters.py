"""Tests for PSP parameters — HR-14,15,16 from HR_UKRAINE.md.

Tests cover:
- PSP parameters creation
- Computed fields (psp_standard, psp_150, psp_200, income_limit, max_esv_base)
- Parameter lookup by date
"""

from datetime import date
from odoo.tests import tagged
from odoo.tools import float_round
from .common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestPspParameters(SalaryTestCase):
    """Test hr.psp.parameters model."""

    def test_psp_params_creation(self):
        """Parameters should store year and base values."""
        self.assertEqual(self.psp_params.year, 2025)
        self.assertGreater(self.psp_params.subsistence_minimum, 0)
        self.assertGreater(self.psp_params.min_wage, 0)

    def test_psp_standard_computed(self):
        """Standard PSP = 50% of subsistence minimum."""
        expected = self.psp_params.subsistence_minimum * 0.5
        self.assertAlmostEqual(self.psp_params.psp_standard, expected, places=2)

    def test_psp_150_computed(self):
        """150% PSP = 75% of subsistence minimum."""
        expected = self.psp_params.subsistence_minimum * 0.75
        self.assertAlmostEqual(self.psp_params.psp_150, expected, places=2)

    def test_psp_200_computed(self):
        """200% PSP = 100% of subsistence minimum."""
        expected = self.psp_params.subsistence_minimum * 1.0
        self.assertAlmostEqual(self.psp_params.psp_200, expected, places=2)

    def test_income_limit_computed(self):
        """Граничний дохід для ПСП = ПМ × 1,4, округлений до найближчих 10 грн (п. 169.4.1 ПКУ)."""
        expected = float_round(self.psp_params.subsistence_minimum * 1.4, precision_rounding=10)
        self.assertAlmostEqual(self.psp_params.income_limit, expected, places=2)

    def test_max_esv_base_computed(self):
        """Max ESV base = 15 * min_wage."""
        expected = 15 * self.psp_params.min_wage
        self.assertAlmostEqual(self.psp_params.max_esv_base, expected, places=2)

    def test_get_parameters(self):
        """get_parameters should find params by date."""
        params = self.env['hr.psp.parameters'].get_parameters(
            date(2025, 6, 15), self.company.id,
        )
        self.assertTrue(params)
        self.assertEqual(params.year, 2025)

    def test_different_year_allowed(self):
        """Different year should be allowed."""
        # Clean up if exists
        existing = self.env['hr.psp.parameters'].search([
            ('year', '=', 2030),
            ('company_id', '=', self.company.id),
        ])
        existing.unlink()

        params_2030 = self.env['hr.psp.parameters'].create({
            'year': 2030,
            'date_from': date(2030, 1, 1),
            'subsistence_minimum': 3300,
            'min_wage': 8500,
            'company_id': self.company.id,
        })
        self.assertEqual(params_2030.year, 2030)
        self.assertAlmostEqual(params_2030.max_esv_base, 15 * 8500, places=2)
