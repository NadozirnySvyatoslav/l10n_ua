"""Tests for payment approval workflow — from ACCOUNTING_UKRAINE.md control mechanisms.

Tests cover:
- Threshold-based approval requirement
- Approve/reject actions
- Blocking post without approval
"""

from odoo.tests import tagged
from odoo.exceptions import UserError
from .common import AccountingTestCase


@tagged('post_install', '-at_install')
class TestPaymentApproval(AccountingTestCase):
    """Test payment approval workflow (затвердження платежів)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Enable approval with threshold 50,000
        cls.company.write({
            'l10n_ua_payment_approval_enabled': True,
            'l10n_ua_payment_approval_threshold': 50000,
        })

    def _create_outbound_payment(self, amount, journal=None):
        """Helper to create an outbound payment."""
        return self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner.id,
            'amount': amount,
            'journal_id': (journal or self.bank_journal).id,
        })

    def test_approval_required_above_threshold(self):
        """Payments above threshold should require approval."""
        payment = self._create_outbound_payment(75000)
        self.assertTrue(payment.ua_approval_required,
                        'Payment above threshold should require approval')

    def test_approval_not_required_below_threshold(self):
        """Payments below threshold should not require approval."""
        payment = self._create_outbound_payment(30000)
        self.assertFalse(payment.ua_approval_required,
                         'Payment below threshold should not require approval')

    def test_approval_not_required_inbound(self):
        """Inbound payments should never require approval."""
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 100000,
            'journal_id': self.bank_journal.id,
        })
        self.assertFalse(payment.ua_approval_required,
                         'Inbound payments should not require approval')

    def test_approve_payment(self):
        """Approving payment should set approved fields."""
        payment = self._create_outbound_payment(75000)
        payment.action_approve()
        self.assertTrue(payment.ua_approved)
        self.assertEqual(payment.ua_approved_by, self.env.user)
        self.assertTrue(payment.ua_approved_date)

    def test_reject_payment(self):
        """Rejecting should clear approval fields."""
        payment = self._create_outbound_payment(75000)
        payment.action_approve()
        self.assertTrue(payment.ua_approved)
        payment.action_reject()
        self.assertFalse(payment.ua_approved)
        self.assertFalse(payment.ua_approved_by)

    def test_post_blocked_without_approval(self):
        """Posting should be blocked if approval is required but not given."""
        payment = self._create_outbound_payment(75000)
        with self.assertRaises(Exception):
            payment.action_post()

    def test_post_allowed_with_approval(self):
        """Posting should work after approval."""
        payment = self._create_outbound_payment(75000)
        payment.action_approve()
        # Should not raise
        payment.action_post()
        # Odoo 20 replaced the payment states posted/in_process/sent
        # with paid/reconciled.
        self.assertIn(payment.state, ('paid', 'reconciled'),
                      'Payment should be paid or reconciled after action_post')

    def test_post_allowed_below_threshold(self):
        """Posting should work without approval when below threshold."""
        payment = self._create_outbound_payment(30000)
        payment.action_post()
        # Odoo 20 replaced the payment states posted/in_process/sent
        # with paid/reconciled.
        self.assertIn(payment.state, ('paid', 'reconciled'),
                      'Payment should be paid or reconciled after action_post')

    def test_approval_disabled(self):
        """When approval is disabled, no payments should require approval."""
        self.company.l10n_ua_payment_approval_enabled = False
        payment = self._create_outbound_payment(100000)
        self.assertFalse(payment.ua_approval_required)
        # Should be able to post
        payment.action_post()
        # Odoo 20 replaced the payment states posted/in_process/sent
        # with paid/reconciled.
        self.assertIn(payment.state, ('paid', 'reconciled'),
                      'Payment should be paid or reconciled after action_post')
