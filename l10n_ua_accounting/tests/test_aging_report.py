"""Tests for AR/AP aging report — from ACCOUNTING_UKRAINE.md weekly tasks.

Tests cover:
- Report creation
- Computation of aging buckets
- State workflow
- XLSX export
"""

from datetime import date
from odoo.tests import tagged
from .common import AccountingTestCase


@tagged('post_install', '-at_install')
class TestAgingReport(AccountingTestCase):
    """Test AR/AP aging report (заборгованість)."""

    def _create_aging_report(self, report_type='receivable'):
        """Helper to create an aging report."""
        return self.env['l10n_ua.aging.report'].create({
            'date': date.today(),
            'report_type': report_type,
            'company_id': self.company.id,
        })

    def test_aging_report_creation(self):
        """Aging report should be created in draft state."""
        report = self._create_aging_report()
        self.assertEqual(report.state, 'draft')
        self.assertTrue(report.name)

    def test_aging_report_receivable_name(self):
        """Receivable report should have appropriate name."""
        report = self._create_aging_report('receivable')
        self.assertIn('Дебіторська', report.name)

    def test_aging_report_payable_name(self):
        """Payable report should have appropriate name."""
        report = self._create_aging_report('payable')
        self.assertIn('Кредиторська', report.name)

    def test_aging_report_compute(self):
        """Computing should change state to calculated."""
        report = self._create_aging_report()
        report.action_compute()
        self.assertEqual(report.state, 'calculated')

    def test_aging_report_confirm(self):
        """Should be able to confirm a calculated report."""
        report = self._create_aging_report()
        report.action_compute()
        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')

    def test_aging_report_draft_reset(self):
        """Should be able to reset to draft."""
        report = self._create_aging_report()
        report.action_compute()
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_aging_report_both_type(self):
        """Should be able to create a 'both' type report."""
        report = self._create_aging_report('both')
        report.action_compute()
        self.assertEqual(report.state, 'calculated')

    def test_aging_bucket_classification(self):
        """Test internal bucket classification method."""
        report = self._create_aging_report()
        self.assertEqual(report._get_bucket(0), 'current')
        self.assertEqual(report._get_bucket(5), '1_7')
        self.assertEqual(report._get_bucket(10), '8_14')
        self.assertEqual(report._get_bucket(20), '15_30')
        self.assertEqual(report._get_bucket(45), '31_60')
        self.assertEqual(report._get_bucket(75), '61_90')
        self.assertEqual(report._get_bucket(120), 'over_90')

    def test_aging_report_xlsx_export(self):
        """XLSX export should return an action with file data."""
        report = self._create_aging_report()
        report.action_compute()
        result = report.action_export_xlsx()
        self.assertIsInstance(result, dict)
        self.assertXlsxExport(result)
