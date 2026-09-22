"""Tests for VAT registers — Flow 6 from ACCOUNTING_UKRAINE.md.

Tests cover:
- Register creation (issued/received)
- Auto-fill from tax invoices
- Line totals computation
- State workflow
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVatRegister(TransactionCase):
    """Test VAT registers (реєстри ПН)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Контрагент ПДВ',
        })
        cls.company.l10n_ua_is_vat_payer = True
        # Create tax period
        cls.period = cls.env['l10n_ua.tax.period'].search([
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.period:
            cls.period = cls.env['l10n_ua.tax.period'].create({
                'name': 'Червень 2025',
                'date_start': date(2025, 6, 1),
                'date_end': date(2025, 6, 30),
                'period_type': 'month',
                'month': 6,
                'year': 2025,
                'quarter': 2,
                'company_id': cls.company.id,
            })

    def _create_register(self, register_type='issued'):
        return self.env['l10n_ua.vat.register'].create({
            'register_type': register_type,
            'period_id': self.period.id,
            'company_id': self.company.id,
        })

    def test_register_creation(self):
        """VAT register should be created in draft state."""
        reg = self._create_register()
        self.assertEqual(reg.state, 'draft')
        self.assertTrue(reg.name)

    def test_register_issued_name(self):
        """Issued register should contain 'видані' in name."""
        reg = self._create_register('issued')
        name_lower = reg.name.lower()
        self.assertTrue(
            'видан' in name_lower or 'issued' in name_lower,
            f'Issued register name should indicate type: {reg.name}',
        )

    def test_register_received_name(self):
        """Received register should contain 'отримані' in name."""
        reg = self._create_register('received')
        name_lower = reg.name.lower()
        self.assertTrue(
            'отриман' in name_lower or 'received' in name_lower,
            f'Received register name should indicate type: {reg.name}',
        )

    def test_register_confirm(self):
        """Confirming should change state."""
        reg = self._create_register()
        reg.action_confirm()
        self.assertEqual(reg.state, 'confirmed')

    def test_register_draft_from_confirmed(self):
        """Should be able to go back to draft."""
        reg = self._create_register()
        reg.action_confirm()
        reg.action_draft()
        self.assertEqual(reg.state, 'draft')

    def test_register_totals_empty(self):
        """Empty register should have zero totals."""
        reg = self._create_register()
        self.assertEqual(reg.total_base, 0)
        self.assertEqual(reg.total_vat, 0)
        self.assertEqual(reg.line_count, 0)

    def test_register_compute_from_invoices(self):
        """action_compute should fill lines from tax invoices."""
        # Create a tax invoice in this period
        self.env['l10n_ua.tax.invoice'].create({
            'doc_type': 'pn',
            'number': '100',
            'date': date(2025, 6, 15),
            'invoice_type': 'issued',
            'partner_id': self.partner.id,
            'company_id': self.company.id,
            'state': 'registered',
            'line_ids': [(0, 0, {
                'name': 'Послуга',
                'quantity': 1,
                'price_unit': 50000,
                'vat_rate': '20',
            })],
        })
        reg = self._create_register('issued')
        reg.action_compute()
        self.assertTrue(reg.line_ids, 'Register should have lines after compute')
