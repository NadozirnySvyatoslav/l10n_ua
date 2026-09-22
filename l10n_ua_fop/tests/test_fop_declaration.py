"""Tests for FOP declaration — from ACCOUNTING_UKRAINE.md single tax.

Tests cover:
- Declaration creation
- Income calculation from books
- Tax and ESV computation
- Income limit check
- State workflow
"""

from datetime import date
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFopDeclaration(TransactionCase):
    """Test FOP declaration (декларація єдиного податку)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.fop_group_3 = cls.env['l10n_ua.fop.group'].search([
            ('code', '=', '3'),
        ], limit=1)
        if not cls.fop_group_3:
            cls.fop_group_3 = cls.env['l10n_ua.fop.group'].create({
                'code': '3',
                'name': '3 група (без ПДВ)',
                'tax_rate': 5.0,
                'limit_min_wages': 1167,
            })

    def _create_income_books(self, year=2025):
        """Create confirmed income books for all 4 quarters."""
        books = []
        amounts = [60000, 70000, 80000, 90000]
        for q, amount in zip(['1', '2', '3', '4'], amounts):
            book = self.env['l10n_ua.fop.income.book'].create({
                'year': year,
                'quarter': q,
                'fop_group_id': self.fop_group_3.id,
                'company_id': self.company.id,
            })
            month_start = {'1': 1, '2': 4, '3': 7, '4': 10}[q]
            self.env['l10n_ua.fop.income.book.line'].create({
                'book_id': book.id,
                'date': date(year, month_start, 15),
                'amount': amount,
                'description': f'Дохід Q{q}',
            })
            book.action_confirm()
            books.append(book)
        return books

    def _create_declaration(self, period='year', year=2025):
        return self.env['l10n_ua.fop.declaration'].create({
            'year': year,
            'period': period,
            'fop_group_id': self.fop_group_3.id,
            'company_id': self.company.id,
        })

    def test_declaration_creation(self):
        """Declaration should be created in draft state."""
        decl = self._create_declaration()
        self.assertEqual(decl.state, 'draft')
        self.assertTrue(decl.name)

    def test_declaration_calculate_from_books(self):
        """Calculate should pull income from confirmed income books."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        self.assertEqual(decl.state, 'calculated')
        self.assertEqual(decl.total_income, 300000)  # 60+70+80+90

    def test_declaration_tax_calculation_group3(self):
        """Group 3 (5%): single tax = total_income × 5%."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        self.assertEqual(decl.single_tax, 15000)  # 300000 × 5%

    def test_declaration_esv_calculation(self):
        """ЄСВ = мінзарплата з довідника (2025 — 8000) × місяці × 22%."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        self.assertEqual(decl.min_wage, 8000)
        # ESV for year: 8000 × 12 × 22% = 21,120
        self.assertEqual(decl.esv_base, 96000)  # 8000 × 12
        self.assertAlmostEqual(decl.esv_amount, 21120, places=2)

    def test_declaration_q1_period(self):
        """Q1 declaration should only include Q1 income."""
        self._create_income_books()
        decl = self._create_declaration('q1', 2025)
        decl.action_calculate()
        self.assertEqual(decl.total_income, 60000)

    def test_declaration_h1_period(self):
        """H1 declaration should include Q1 + Q2."""
        self._create_income_books()
        decl = self._create_declaration('h1', 2025)
        decl.action_calculate()
        self.assertEqual(decl.total_income, 130000)  # 60+70

    def test_declaration_state_workflow(self):
        """State: draft → calculated → submitted → accepted."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        self.assertEqual(decl.state, 'calculated')
        # action_submit тепер відкриває КЕП-підпис (l10n_ua.dps.submit.mixin);
        # 'submitted' виставляє _dps_on_submitted за квитанцією. Повний КЕП-потік
        # покрито тестами ЄРПН; тут перевіряємо лише машину станів.
        decl._dps_on_submitted('ok')
        self.assertEqual(decl.state, 'submitted')
        decl.action_accept()
        self.assertEqual(decl.state, 'accepted')

    def test_declaration_income_limit_not_exceeded(self):
        """Normal income should not trigger limit warning."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        self.assertFalse(decl.income_limit_exceeded)

    def test_esv_months_by_period(self):
        """ESV months should match period: q1=3, h1=6, 9m=9, year=12."""
        for period, expected_months in [('q1', 3), ('h1', 6), ('9m', 9), ('year', 12)]:
            decl = self._create_declaration(period, 2025)
            self.assertEqual(decl.esv_months, expected_months,
                             f'Period {period} should have {expected_months} ESV months')
            decl.unlink()

    def test_generate_xml_requires_calculation(self):
        """action_generate_xml must refuse a draft declaration — issue #139."""
        decl = self._create_declaration('year', 2025)
        self.assertEqual(decl.state, 'draft')
        with self.assertRaises(UserError):
            decl.action_generate_xml()

    def test_generate_xml_delegates_to_F0103309(self):
        """XML is built via the canonical F0103309 generator, not a stub — issue #139."""
        self._create_income_books()
        decl = self._create_declaration('year', 2025)
        decl.action_calculate()
        result = decl.action_generate_xml()
        self.assertTrue(result)
        self.assertTrue(decl.xml_file, 'xml_file must be populated')
        self.assertTrue(decl.xml_filename.endswith('_F0103309.xml'))

        xml = decl.xml_file.content.decode('windows-1251')
        # Canonical F0103309 structure and the declaration's own figures.
        self.assertIn('<C_DOC>F01</C_DOC>', xml)
        self.assertIn('<C_DOC_SUB>033</C_DOC_SUB>', xml)
        self.assertIn('<HY>1</HY>', xml)              # annual → year marker
        self.assertIn('<PERIOD_TYPE>5</PERIOD_TYPE>', xml)
        self.assertIn('<R006G3>300000.00</R006G3>', xml)  # total income
        self.assertIn('<R011G3>15000.00</R011G3>', xml)   # single tax 5%
        self.assertIn('<R023G3>3000.00</R023G3>', xml)    # military levy 1%
        # Structural elements the DPS XSD requires (verified against a real
        # accepted CABINET declaration — see F0103309 renderer).
        self.assertIn('<LINKED_DOCS xsi:nil="true"/>', xml)
        self.assertIn('<SOFTWARE>', xml)
        self.assertIn('<T2RXXXXG2S ROWNUM="1" xsi:nil="true"/>', xml)

    def test_generate_xml_quarter_marker_matches_period(self):
        """Each reporting period maps to the F0103309 body period marker — issue #139.

        Markers звірені з офіційним XSD ДПС (DBody: H1KV/HHY/H3KV/HY) —
        див. l10n_ua_tax_F0103309/tests/test_xsd_validation.py.
        """
        self._create_income_books()
        cases = {'q1': 'H1KV', 'h1': 'HHY', '9m': 'H3KV', 'year': 'HY'}
        for period, marker in cases.items():
            decl = self._create_declaration(period, 2025)
            decl.action_calculate()
            decl.action_generate_xml()
            xml = decl.xml_file.content.decode('windows-1251')
            self.assertIn(f'<{marker}>1</{marker}>', xml,
                          f'Period {period} should emit marker {marker}')
            decl.unlink()
