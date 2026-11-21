"""Tests for MNMA (low-value non-current tangible assets).

Tests cover:
- MNMA creation
- 50/50 and 100% write-off methods
- Depreciation computation
- State workflow (draft → in_use → written_off)
"""

from datetime import date
from odoo.exceptions import UserError
from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMnma(TransactionCase):
    """Test MNMA (малоцінні необоротні матеріальні активи)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

    def _create_mnma(self, write_off_method='50_50', value=5000):
        return self.env['l10n_ua.mnma'].create({
            'name': 'Принтер HP LaserJet',
            'date': date(2025, 3, 1),
            'original_value': value,
            'write_off_method': write_off_method,
            'company_id': self.company.id,
        })

    def test_mnma_creation(self):
        """MNMA should be created in draft state."""
        mnma = self._create_mnma()
        self.assertEqual(mnma.state, 'draft')
        self.assertTrue(mnma.name)

    def test_mnma_50_50_before_commission(self):
        """Before commissioning, no depreciation in 50/50 method."""
        mnma = self._create_mnma('50_50', 6000)
        self.assertEqual(mnma.residual_value, 6000)

    def test_mnma_50_50_commissioning(self):
        """50/50: first 50% on commissioning, remainder stays until write-off."""
        mnma = self._create_mnma('50_50', 6000)
        mnma.action_commission()
        self.assertEqual(mnma.state, 'in_use')
        self.assertEqual(mnma.depreciation_value, 3000)  # 50% of 6000
        self.assertEqual(mnma.residual_value, 3000)
        self.assertTrue(mnma.commission_date)
        self.assertTrue(mnma.commission_act_number)

    def test_mnma_50_50_writeoff(self):
        """50/50: remaining 50% depreciated on write-off."""
        mnma = self._create_mnma('50_50', 6000)
        mnma.action_commission()
        mnma.action_write_off()
        self.assertEqual(mnma.state, 'written_off')
        self.assertEqual(mnma.depreciation_value, 6000)  # 100% now
        self.assertEqual(mnma.residual_value, 0)

    def test_mnma_100_commissioning(self):
        """100%: full depreciation on commissioning."""
        mnma = self._create_mnma('100', 4000)
        mnma.action_commission()
        self.assertEqual(mnma.state, 'in_use')
        self.assertEqual(mnma.depreciation_value, 4000)
        self.assertEqual(mnma.residual_value, 0)

    def test_mnma_100_writeoff(self):
        """100%: write-off after full depreciation should have zero residual."""
        mnma = self._create_mnma('100', 4000)
        mnma.action_commission()
        mnma.action_write_off()
        self.assertEqual(mnma.state, 'written_off')
        self.assertEqual(mnma.residual_value, 0)

    def test_mnma_draft_from_draft(self):
        """MNMA in draft should be modifiable."""
        mnma = self._create_mnma()
        mnma.write({'name': 'Оновлена назва'})
        self.assertEqual(mnma.name, 'Оновлена назва')

    # --- #626: дата документа замість «сьогодні» ---

    def test_document_date_defaults_to_today(self):
        mnma = self._create_mnma()
        self.assertEqual(mnma.document_date, fields.Date.context_today(mnma))

    def test_commission_and_writeoff_use_document_date(self):
        mnma = self._create_mnma()
        mnma.document_date = date(2025, 3, 10)
        mnma.action_commission()
        self.assertEqual(mnma.commission_date, date(2025, 3, 10))
        # Поле очищується під наступний документ.
        self.assertFalse(mnma.document_date)
        mnma.document_date = date(2025, 9, 30)
        mnma.action_write_off()
        self.assertEqual(mnma.writeoff_date, date(2025, 9, 30))

    def test_empty_document_date_means_today(self):
        mnma = self._create_mnma()
        mnma.document_date = False
        mnma.action_commission()
        self.assertEqual(mnma.commission_date, fields.Date.context_today(mnma))

    def test_writeoff_before_commission_raises(self):
        mnma = self._create_mnma()
        mnma.document_date = date(2025, 3, 10)
        mnma.action_commission()
        mnma.document_date = date(2025, 3, 9)
        with self.assertRaises(UserError):
            mnma.action_write_off()
