"""Ручне заведення банківської транзакції з кореспондентним рахунком.

У Community немає вікна звірки, тож рядок виписки рознесено одразу на
обраний рахунок (статутний капітал, фіндопомога, комісія) замість suspense.
"""

from odoo.exceptions import UserError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestManualTransaction(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'UA Bank MT', 'type': 'bank', 'code': 'MTBK',
            'company_id': cls.company.id})
        Account = cls.env['account.account']
        cls.acc_equity = Account.create({
            'code': '469901', 'name': 'Внески до капіталу (тест)',
            'account_type': 'asset_receivable', 'reconcile': True})
        cls.acc_fee = Account.create({
            'code': '929901', 'name': 'Комісія банку (тест)',
            'account_type': 'expense'})
        cls.StLine = cls.env['account.bank.statement.line']

    def _accounts(self, st_line):
        return {(l.account_id, l.debit, l.credit) for l in st_line.move_id.line_ids}

    def test_create_with_counterpart_account(self):
        st_line = self.StLine.create({
            'journal_id': self.journal.id, 'date': '2026-10-14',
            'payment_ref': 'Внесок до статутного капіталу', 'amount': 1000.0,
            'l10n_ua_counterpart_account_id': self.acc_equity.id})
        self.assertEqual(self._accounts(st_line), {
            (self.journal.default_account_id, 1000.0, 0.0),
            (self.acc_equity, 0.0, 1000.0)})
        self.assertTrue(st_line.is_reconciled)
        self.assertEqual(st_line.move_id.state, 'posted')

    def test_without_counterpart_uses_suspense(self):
        st_line = self.StLine.create({
            'journal_id': self.journal.id, 'date': '2026-10-14',
            'payment_ref': 'Невідомий платіж', 'amount': 50.0})
        self.assertIn(self.journal.suspense_account_id, st_line.move_id.line_ids.account_id)
        self.assertFalse(st_line.is_reconciled)
        st_line.amount = 60.0
        self.assertEqual(self._accounts(st_line), {
            (self.journal.default_account_id, 60.0, 0.0),
            (self.journal.suspense_account_id, 0.0, 60.0)})

    def test_set_change_and_clear_counterpart(self):
        st_line = self.StLine.create({
            'journal_id': self.journal.id, 'date': '2026-10-14',
            'payment_ref': 'Комісія банку', 'amount': -25.0})
        st_line.l10n_ua_counterpart_account_id = self.acc_fee
        self.assertEqual(self._accounts(st_line), {
            (self.journal.default_account_id, 0.0, 25.0),
            (self.acc_fee, 25.0, 0.0)})
        self.assertTrue(st_line.is_reconciled)
        # Зміна суми зберігає обраний рахунок.
        st_line.amount = -30.0
        self.assertEqual(self._accounts(st_line), {
            (self.journal.default_account_id, 0.0, 30.0),
            (self.acc_fee, 30.0, 0.0)})
        st_line.l10n_ua_counterpart_account_id = False
        self.assertIn(self.journal.suspense_account_id, st_line.move_id.line_ids.account_id)
        self.assertFalse(st_line.is_reconciled)

    def test_cannot_change_reconciled_counterpart(self):
        st_line = self.StLine.create({
            'journal_id': self.journal.id, 'date': '2026-10-14',
            'payment_ref': 'Внесок', 'amount': 200.0,
            'l10n_ua_counterpart_account_id': self.acc_equity.id})
        debt = self.env['account.move'].create({
            'move_type': 'entry', 'date': '2026-10-01',
            'line_ids': [
                (0, 0, {'account_id': self.acc_equity.id, 'debit': 200.0}),
                (0, 0, {'account_id': self.acc_fee.id, 'credit': 200.0}),
            ]})
        debt.action_post()
        (st_line.move_id.line_ids | debt.line_ids).filtered(
            lambda l: l.account_id == self.acc_equity).reconcile()
        with self.assertRaises(UserError):
            st_line.l10n_ua_counterpart_account_id = self.acc_fee

    def test_form_view_creates_transaction(self):
        action = self.env.ref('l10n_ua_bank_sync.l10n_ua_bank_transaction_action')
        form_view = action.view_ids.filtered(lambda v: v.view_mode == 'form').view_id
        self.assertEqual(form_view, self.env.ref('l10n_ua_bank_sync.l10n_ua_bank_transaction_view_form'))
        with Form(self.StLine, view=form_view) as f:
            f.journal_id = self.journal
            f.date = '2026-10-14'
            f.payment_ref = 'Повернення фіндопомоги'
            f.amount = -300.0
            f.l10n_ua_counterpart_account_id = self.acc_equity
        st_line = f.record
        self.assertEqual(self._accounts(st_line), {
            (self.journal.default_account_id, 0.0, 300.0),
            (self.acc_equity, 300.0, 0.0)})
