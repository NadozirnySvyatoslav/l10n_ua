"""Tests for VAT declaration — Flow 6 from ACCOUNTING_UKRAINE.md.

Tests cover:
- Declaration creation
- Auto-calculation from registers
- VAT payable/refundable computation
- State workflow
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVatDeclaration(TransactionCase):
    """Test VAT declaration (декларація з ПДВ)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.l10n_ua_is_vat_payer = True
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Декларація Тест',
        })
        cls.period = cls.env['l10n_ua.tax.period'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['l10n_ua.tax.period'].create({
                'name': 'Липень 2025',
                'date_start': date(2025, 7, 1),
                'date_end': date(2025, 7, 31),
                'period_type': 'month',
                'month': 7,
                'year': 2025,
                'quarter': 3,
                'company_id': cls.company.id,
            })

    def _create_declaration(self):
        return self.env['l10n_ua.vat.declaration'].create({
            'period_id': self.period.id,
            'company_id': self.company.id,
        })

    def test_declaration_creation(self):
        """Declaration should be created in draft state."""
        decl = self._create_declaration()
        self.assertEqual(decl.state, 'draft')

    def test_declaration_calculate(self):
        """Calculate should change state to calculated."""
        decl = self._create_declaration()
        decl.action_calculate()
        self.assertEqual(decl.state, 'calculated')

    def test_declaration_state_workflow(self):
        """State: draft → calculated → submitted → accepted."""
        decl = self._create_declaration()
        decl.action_calculate()
        self.assertEqual(decl.state, 'calculated')
        decl.action_submit()
        self.assertEqual(decl.state, 'submitted')
        decl.action_accept()
        self.assertEqual(decl.state, 'accepted')

    def test_declaration_draft_from_calculated(self):
        """Should be able to go back to draft from calculated."""
        decl = self._create_declaration()
        decl.action_calculate()
        decl.action_draft()
        self.assertEqual(decl.state, 'draft')

    def test_vat_payable_calculation(self):
        """When liabilities > credit, VAT should be payable."""
        decl = self._create_declaration()
        decl.write({
            'line_1_1_base': 100000,
            'line_1_1_vat': 20000,
            'line_10_1_base': 50000,
            'line_10_1_vat': 10000,
        })
        # Total liability: 20000, total credit: 10000, payable: 10000
        self.assertEqual(decl.line_9_vat, 20000, 'Total tax liabilities should be 20000')
        self.assertEqual(decl.line_17_vat, 10000, 'Total tax credit should be 10000')
        self.assertEqual(decl.line_18_vat, 10000, 'VAT payable should be 10000')
        self.assertEqual(decl.line_20_vat, 0, 'VAT refundable should be 0')

    def test_vat_refundable_calculation(self):
        """When credit > liabilities, VAT should be refundable."""
        decl = self._create_declaration()
        decl.write({
            'line_1_1_base': 50000,
            'line_1_1_vat': 10000,
            'line_10_1_base': 100000,
            'line_10_1_vat': 20000,
        })
        self.assertEqual(decl.line_18_vat, 0, 'VAT payable should be 0')
        self.assertEqual(decl.line_20_vat, 10000, 'VAT refundable should be 10000')
