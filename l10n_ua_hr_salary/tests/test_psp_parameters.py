"""Tests for PSP parameters — HR-14,15,16 from HR_UKRAINE.md.

Tests cover:
- PSP parameters creation
- Computed fields (psp_standard, psp_150, psp_200, income_limit, max_esv_base)
- Parameter lookup by date
"""

from datetime import date
from odoo.tests import TransactionCase, tagged
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
        """Max ESV base = minimum wage × the multiplier of the period."""
        expected = self.psp_params.max_esv_base_multiplier * self.psp_params.min_wage
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
        # No budget law known for the year: the ESV law's 15 minimum wages.
        self.assertAlmostEqual(params_2030.max_esv_base, 15 * 8500, places=2)
        params_2030.max_esv_base_multiplier = 20
        self.assertAlmostEqual(params_2030.max_esv_base, 20 * 8500, places=2)




@tagged('post_install', '-at_install')
class TestPspParametersCompanyScope(TransactionCase):
    """Every company keeps its own parameters; none is shared or a template."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env['res.company'].create({'name': 'PSP Scope A'})
        cls.company_b = cls.env['res.company'].create({'name': 'PSP Scope B'})
        cls.Params = cls.env['hr.psp.parameters'].with_context(active_test=False)
        cls.templates = cls.env['hr.psp.parameters.template'].search([])

    def _own(self, company, date_from):
        return self.Params.search([
            ('company_id', '=', company.id), ('date_from', '=', date_from)])

    def test_no_shared_records(self):
        self.assertFalse(self.Params.search([('company_id', '=', False)]))

    def test_no_company_records_tied_to_module_data(self):
        self.assertFalse(self.env['ir.model.data'].search([
            ('module', '=', 'l10n_ua_hr_salary'),
            ('model', '=', 'hr.psp.parameters'),
        ]))

    def test_reference_is_loaded_from_module_data(self):
        template = self.env.ref('l10n_ua_hr_salary.psp_template_2026_01')
        self.assertEqual(template.min_wage, 8647)
        self.assertNotIn('company_id', template._fields)

    def test_new_company_gets_every_statutory_period(self):
        self.assertTrue(self.templates)
        for company in (self.company_a, self.company_b):
            for template in self.templates:
                with self.subTest(company=company.name, period=template.date_from):
                    own = self._own(company, template.date_from)
                    self.assertEqual(len(own), 1)
                    self.assertEqual(own.min_wage, template.min_wage)
                    self.assertEqual(own.subsistence_minimum,
                                     template.subsistence_minimum)
                    self.assertEqual(own.min_hourly_wage, template.min_hourly_wage)

    def test_new_company_gets_module_values_not_another_company_edits(self):
        self._own(self.company_a, '2026-01-01').min_wage = 20000
        company_c = self.env['res.company'].create({'name': 'PSP Scope C'})
        self.assertEqual(self._own(company_c, '2026-01-01').min_wage, 8647)
        self.assertEqual(self._own(self.company_b, '2026-01-01').min_wage, 8647)

    def test_seeding_keeps_edited_records(self):
        own_a = self._own(self.company_a, '2026-01-01')
        own_a.min_wage = 20000
        self.Params._seed_company_parameters()
        self.assertEqual(self._own(self.company_a, '2026-01-01'), own_a)
        self.assertEqual(own_a.min_wage, 20000)

    def test_deleted_period_not_brought_back(self):
        self._own(self.company_a, '2024-01-01').unlink()
        self.Params._seed_company_parameters()
        self.assertFalse(self._own(self.company_a, '2024-01-01'))

    def test_new_period_reaches_every_company(self):
        self.templates.filtered(lambda t: not t.date_to).date_to = date(2030, 12, 31)
        self.env['hr.psp.parameters.template'].create({
            'year': 2031, 'date_from': date(2031, 1, 1),
            'subsistence_minimum': 4000, 'min_wage': 10000, 'min_hourly_wage': 60,
        })
        self.Params._seed_company_parameters()
        for company in (self.company_a, self.company_b):
            self.assertEqual(self._own(company, '2031-01-01').min_wage, 10000)

    def test_lookup_ignores_other_companies(self):
        own_b = self.Params.create({
            'year': 2031,
            'date_from': date(2031, 1, 1),
            'subsistence_minimum': 4000,
            'min_wage': 12000,
            'company_id': self.company_b.id,
        })
        self.assertEqual(
            self.Params.get_parameters(date(2031, 6, 1), self.company_b.id), own_b)
        # Company A falls back to its own open-ended latest record, never to B's.
        self.assertEqual(
            self.Params.get_parameters(date(2031, 6, 1), self.company_a.id),
            self._own(self.company_a, '2027-01-01'))

    def test_2027_period(self):
        """#351: 2026 закрито, з 01.01.2027 — мінзарплата 9546, ПМ 3691."""
        params_2026 = self.Params.get_parameters(date(2026, 12, 31), self.company_a.id)
        params_2027 = self.Params.get_parameters(date(2027, 1, 1), self.company_a.id)
        self.assertEqual(params_2026.date_to, date(2026, 12, 31))
        self.assertEqual(params_2026.min_wage, 8647)
        self.assertEqual(params_2027.min_wage, 9546)
        self.assertEqual(params_2027.subsistence_minimum, 3691)
        self.assertEqual(params_2027.min_hourly_wage, 57.5)

    def test_default_company_is_the_active_one(self):
        Params = self.env['hr.psp.parameters'].with_company(self.company_b)
        self.assertEqual(Params.get_parameters(date(2026, 6, 1)),
                         self._own(self.company_b, '2026-01-01'))

    def test_fill_gaps_restores_history_behind_a_later_record(self):
        """The 19.0.1.4.5 migration hands a company without records of its
        own copies of the shared ones; if those are for a later period, the
        ordinary seeding sees them as the company's latest and adds nothing
        before them. Filling the gaps gives the company its whole history."""
        company_c = self.env['res.company'].create({'name': 'PSP Scope C'})
        self.Params.search([('company_id', '=', company_c.id)]).unlink()
        later = self.Params.create({
            'year': 2031, 'date_from': date(2031, 1, 1),
            'subsistence_minimum': 4000, 'min_wage': 10000,
            'company_id': company_c.id,
        })

        self.Params._seed_company_parameters(company_c)
        self.assertEqual(
            self.Params.search([('company_id', '=', company_c.id)]), later)

        self.Params._seed_company_parameters(company_c, fill_gaps=True)
        for template in self.templates:
            with self.subTest(period=template.date_from):
                self.assertEqual(len(self._own(company_c, template.date_from)), 1)
        self.assertEqual(later.min_wage, 10000)
        # Idempotent: a second run finds nothing missing.
        self.assertFalse(
            self.Params._seed_company_parameters(company_c, fill_gaps=True))
