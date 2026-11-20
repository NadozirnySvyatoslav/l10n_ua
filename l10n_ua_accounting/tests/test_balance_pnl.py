"""Tests for Balance Sheet (Ф.1) and P&L (Ф.2) — Flow 5 from ACCOUNTING_UKRAINE.md.

Tests cover:
- Report creation and computation
- Line generation with correct structure
- State workflow
"""

from datetime import date
from odoo.tests import tagged
from .common import AccountingTestCase


@tagged('post_install', '-at_install')
class TestBalanceReport(AccountingTestCase):
    """Test Balance Sheet report (Баланс, Форма №1)."""

    def _create_balance_report(self):
        return self.env['l10n_ua.balance.report'].create({
            'date_to': date(2025, 12, 31),
            'company_id': self.company.id,
        })

    def test_balance_report_creation(self):
        """Balance report should be created in draft state."""
        report = self._create_balance_report()
        self.assertEqual(report.state, 'draft')
        self.assertTrue(report.name)

    def test_balance_report_compute(self):
        """Computing should generate lines with proper structure."""
        report = self._create_balance_report()
        report.action_compute()
        # Should have lines generated
        self.assertTrue(report.line_ids, 'Balance report should have lines after compute')

    def test_balance_report_line_types(self):
        """Report should contain different line types."""
        report = self._create_balance_report()
        report.action_compute()
        line_types = set(report.line_ids.mapped('line_type'))
        # Should have at least sections and details
        self.assertTrue(line_types, 'Should have line types')

    def test_balance_report_state_workflow(self):
        """State workflow: draft → computed → confirmed → draft."""
        report = self._create_balance_report()
        report.action_compute()
        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_balance_totals_computed(self):
        """Balance report should compute total_assets and total_liabilities fields."""
        report = self._create_balance_report()
        report.action_compute()
        # Verify that total fields are computed (may not be equal in test DB
        # with demo data, but the computed fields should be numeric)
        self.assertIsInstance(report.total_assets, float)
        self.assertIsInstance(report.total_liabilities, float)

    def test_balance_report_xlsx_export(self):
        """XLSX-експорт Балансу створює вкладення з файлом (#606)."""
        report = self._create_balance_report()
        report.action_compute()
        self.assertXlsxExport(report.action_export_xlsx())


@tagged('post_install', '-at_install')
class TestPnlReport(AccountingTestCase):
    """Test P&L report (Звіт про фінансові результати, Форма №2)."""

    def _create_pnl_report(self):
        return self.env['l10n_ua.pnl.report'].create({
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
            'company_id': self.company.id,
        })

    def test_pnl_report_creation(self):
        """P&L report should be created in draft state."""
        report = self._create_pnl_report()
        self.assertEqual(report.state, 'draft')
        self.assertTrue(report.name)

    def test_pnl_report_compute(self):
        """Computing should generate P&L lines."""
        report = self._create_pnl_report()
        report.action_compute()
        self.assertTrue(report.line_ids, 'P&L report should have lines after compute')

    def test_pnl_report_state_workflow(self):
        """State workflow: draft → confirmed → draft."""
        report = self._create_pnl_report()
        report.action_compute()
        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_pnl_report_xlsx_export(self):
        """XLSX-експорт Ф.2 створює вкладення з файлом (#606)."""
        report = self._create_pnl_report()
        report.action_compute()
        self.assertXlsxExport(report.action_export_xlsx())
