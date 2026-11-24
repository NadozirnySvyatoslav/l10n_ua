"""Закриття періоду з блокуванням — issue #382.

Odoo 19 не має `period_lock_date`; закриття ставить глобальну дату
блокування (`fiscalyear_lock_date`) і повертає попередню під час скасування.
Рахунки 79x/44x створюються тут, тож тести не пропускаються в базі без плану
рахунків.
"""

from datetime import date

from odoo.exceptions import RedirectWarning, UserError
from odoo.tests import tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestPeriodClosingLock(AccountingTestCase):

    _own_company = True  # #654: demo unreconciled statement lines block the lock

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_92 = cls._account('92', 'Адміністративні витрати', 'expense')
        cls.acc_631 = cls._account('631', 'Розрахунки з постачальниками', 'liability_payable')
        cls.acc_791 = cls._account('791', 'Результат операційної діяльності', 'equity')
        cls.acc_792 = cls._account('792', 'Результат фінансових операцій', 'equity')
        cls.acc_793 = cls._account('793', 'Результат іншої діяльності', 'equity')
        cls.acc_441 = cls._account('4411', 'Нерозподілений прибуток', 'equity')
        cls.acc_442 = cls._account('4421', 'Непокриті збитки', 'equity')
        cls.company.fiscalyear_lock_date = False

    @classmethod
    def _account(cls, code, name, account_type):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [(6, 0, cls.company.ids)],
            'reconcile': account_type == 'liability_payable',
        })

    def _period(self, year, month, last_day):
        return self.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(year, month, 1),
            'date_end': date(year, month, last_day),
            'company_id': self.company.id,
        })

    def _expense(self, on_date, amount=1000.0):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': self.acc_92.id, 'debit': amount,
                        'partner_id': self.partner.id}),
                (0, 0, {'account_id': self.acc_631.id, 'credit': amount,
                        'partner_id': self.partner.id}),
            ],
        })
        move.action_post()
        return move

    def _closing(self, period, **vals):
        values = {
            'period_id': period.id,
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
            'account_791_id': self.acc_791.id,
            'account_792_id': self.acc_792.id,
            'account_793_id': self.acc_793.id,
            'account_profit_id': self.acc_441.id,
            'account_loss_id': self.acc_442.id,
        }
        values.update(vals)
        return self.env['l10n_ua.period.closing'].create(values)

    def test_close_locks_and_reverse_restores_previous_lock(self):
        self.company.fiscalyear_lock_date = date(2032, 12, 31)
        period = self._period(2033, 2, 28)
        self._expense(date(2033, 2, 10))
        closing = self._closing(period)

        closing.action_close()
        self.assertEqual(closing.state, 'closed')
        self.assertEqual(self.company.fiscalyear_lock_date, date(2033, 2, 28))
        self.assertEqual(closing.previous_lock_date, date(2032, 12, 31))

        closing.action_reverse()
        self.assertEqual(closing.state, 'reversed')
        self.assertEqual(self.company.fiscalyear_lock_date, date(2032, 12, 31))
        # The reversals stay in the period instead of being pushed past a lock.
        reversals = self.env['account.move'].search([
            ('reversed_entry_id', 'in', (closing.closing_move_id | closing.retained_move_id).ids),
        ])
        self.assertEqual(len(reversals), 2)
        for move in reversals:
            self.assertEqual(move.state, 'posted')
            self.assertLessEqual(move.date, date(2033, 2, 28))
            self.assertGreaterEqual(move.date, date(2033, 2, 1))

        # Closed again after the reversal, it locks again.
        closing.action_draft()
        closing.action_close()
        self.assertEqual(self.company.fiscalyear_lock_date, date(2033, 2, 28))

    def test_close_without_lock_keeps_lock_date(self):
        period = self._period(2033, 3, 31)
        self._expense(date(2033, 3, 10))
        closing = self._closing(period, lock_period=False)
        closing.action_close()
        self.assertFalse(self.company.fiscalyear_lock_date)
        closing.action_reverse()
        self.assertFalse(self.company.fiscalyear_lock_date)

    def test_later_lock_is_not_moved_back(self):
        """A lock set beyond the period stays as it is, on closing and on reversal."""
        period = self._period(2033, 4, 30)
        self._expense(date(2033, 4, 10))
        closing = self._closing(period)
        self.company.fiscalyear_lock_date = date(2033, 5, 31)
        closing.action_close()
        self.assertEqual(self.company.fiscalyear_lock_date, date(2033, 5, 31))
        self.assertFalse(closing.previous_lock_date)
        self.company.fiscalyear_lock_date = date(2033, 3, 31)
        closing.action_reverse()
        self.assertEqual(self.company.fiscalyear_lock_date, date(2033, 3, 31))

    def test_unreconciled_statement_line_blocks_closing(self):
        """Odoo will not lock a period with unreconciled bank statement lines;
        the closing fails before posting anything."""
        period = self._period(2033, 6, 30)
        self._expense(date(2033, 6, 10))
        self.env['account.bank.statement.line'].create({
            'journal_id': self.bank_journal.id,
            'date': date(2033, 6, 15),
            'payment_ref': 'Невиясненний платіж',
            'amount': 100.0,
        })
        closing = self._closing(period)
        with self.assertRaises(RedirectWarning):
            closing.action_close()
        self.assertEqual(closing.state, 'draft')
        self.assertFalse(closing.closing_move_id)
        self.assertFalse(self.company.fiscalyear_lock_date)

    def test_hard_lock_blocks_reversal(self):
        period = self._period(2033, 7, 31)
        self._expense(date(2033, 7, 10))
        closing = self._closing(period)
        closing.action_close()
        self.company.hard_lock_date = date(2033, 7, 31)
        with self.assertRaises(UserError):
            closing.action_reverse()
        self.assertEqual(closing.state, 'closed')
