"""Витрати/доходи майбутніх періодів (39/69) — issue #372."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestDeferral(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_39 = cls._account('39', 'Витрати майбутніх періодів', 'asset_prepayments')
        cls.acc_69 = cls._account('69', 'Доходи майбутніх періодів', 'liability_current')
        cls.acc_92 = cls._account('92', 'Адміністративні витрати', 'expense')
        cls.acc_703 = cls._account('703', 'Дохід від реалізації послуг', 'income')
        cls.acc_791 = cls._account('791', 'Результат операційної діяльності', 'equity')
        cls.acc_792 = cls._account('792', 'Результат фінансових операцій', 'equity')
        cls.acc_793 = cls._account('793', 'Результат іншої діяльності', 'equity')
        cls.acc_441 = cls._account('4411', 'Нерозподілений прибуток', 'equity')
        cls.acc_442 = cls._account('4421', 'Непокриті збитки', 'equity')
        cls.company.write({
            'l10n_ua_deferred_expense_account_id': cls.acc_39.id,
            'l10n_ua_deferred_revenue_account_id': cls.acc_69.id,
            'l10n_ua_deferral_journal_id': cls.misc_journal.id,
        })

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
        })

    def _deferral(self, **vals):
        values = {
            'kind': 'expense',
            'partner_id': self.partner.id,
            'target_account_id': self.acc_92.id,
            'amount_total': 300.0,
            'date_start': date(2031, 1, 1),
            'date_end': date(2031, 3, 31),
            'method': 'month',
        }
        values.update(vals)
        return self.env['l10n_ua.deferral'].create(values)

    def _period(self, year, month, last_day):
        return self.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(year, month, 1),
            'date_end': date(year, month, last_day),
            'company_id': self.company.id,
        })

    def _closing(self, period):
        return self.env['l10n_ua.period.closing'].create({
            'period_id': period.id,
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
            # the lock itself is covered by test_period_closing_lock
            'lock_period': False,
            'account_791_id': self.acc_791.id,
            'account_792_id': self.acc_792.id,
            'account_793_id': self.acc_793.id,
            'account_profit_id': self.acc_441.id,
            'account_loss_id': self.acc_442.id,
        })

    def _balance(self, account, date_from, date_to):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', account.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ])
        return sum(lines.mapped('balance'))

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    def test_defaults(self):
        deferral = self._deferral()
        self.assertEqual(deferral.deferral_account_id, self.acc_39)
        self.assertEqual(deferral.journal_id, self.misc_journal)
        self.assertNotEqual(deferral.name, '/')
        revenue = self._deferral(kind='revenue', target_account_id=self.acc_703.id)
        self.assertEqual(revenue.deferral_account_id, self.acc_69)

    def test_equal_monthly_sums_to_total(self):
        deferral = self._deferral(amount_total=1000.0)
        deferral.action_compute_schedule()
        self.assertEqual(deferral.line_ids.mapped('amount'), [333.33, 333.33, 333.34])
        self.assertEqual(deferral.line_ids.mapped('date'), [
            date(2031, 1, 31), date(2031, 2, 28), date(2031, 3, 31)])

        yearly = self._deferral(
            amount_total=10000.0, date_end=date(2031, 12, 31))
        yearly.action_compute_schedule()
        self.assertEqual(len(yearly.line_ids), 12)
        self.assertAlmostEqual(sum(yearly.line_ids.mapped('amount')), 10000.0, places=2)
        self.assertEqual(yearly.line_ids[0].amount, 833.33)
        self.assertEqual(yearly.line_ids[-1].amount, 833.37)

    def test_by_days(self):
        # 17 + 28 + 14 = 59 days → 10 per day
        deferral = self._deferral(
            amount_total=590.0, method='day',
            date_start=date(2031, 1, 15), date_end=date(2031, 3, 14))
        deferral.action_compute_schedule()
        self.assertEqual(deferral.line_ids.mapped('amount'), [170.0, 280.0, 140.0])

        # 31 + 15 = 46 days, rounding goes to the last line
        odd = self._deferral(
            amount_total=100.0, method='day',
            date_start=date(2031, 1, 1), date_end=date(2031, 2, 15))
        odd.action_compute_schedule()
        self.assertEqual(odd.line_ids.mapped('amount'), [67.39, 32.61])
        self.assertAlmostEqual(sum(odd.line_ids.mapped('amount')), 100.0, places=2)

    def test_post_due_and_done(self):
        deferral = self._deferral()
        deferral.action_confirm()
        self.assertEqual(deferral.state, 'running')
        self.assertFalse(deferral.initial_move_id, 'manual schedule: amount already on 39')

        deferral.action_post_due(date(2031, 2, 28))
        posted = deferral.line_ids.filtered('is_posted')
        self.assertEqual(len(posted), 2)
        self.assertEqual(deferral.amount_posted, 200.0)
        self.assertEqual(deferral.amount_residual, 100.0)
        move = posted[0].move_id
        debit = move.line_ids.filtered(lambda l: l.debit)
        credit = move.line_ids.filtered(lambda l: l.credit)
        self.assertEqual(debit.account_id, self.acc_92)
        self.assertEqual(credit.account_id, self.acc_39)
        self.assertEqual(debit.debit, 100.0)

        # Re-running posts nothing new
        deferral.action_post_due(date(2031, 2, 28))
        self.assertEqual(len(deferral.line_ids.move_id), 2)

        wizard = self.env['l10n_ua.deferral.post.wizard'].with_context(
            active_model='l10n_ua.deferral', active_ids=deferral.ids,
        ).create({'date': date(2031, 3, 31)})
        wizard.action_post()
        self.assertEqual(deferral.state, 'done')
        self.assertEqual(deferral.amount_residual, 0.0)

        with self.assertRaises(UserError):
            deferral.action_cancel()

    def test_revenue_entries(self):
        deferral = self._deferral(
            kind='revenue', target_account_id=self.acc_703.id, amount_total=600.0)
        deferral.action_confirm()
        deferral.action_post_due(date(2031, 1, 31))
        move = deferral.line_ids[0].move_id
        self.assertEqual(move.line_ids.filtered(lambda l: l.debit).account_id, self.acc_69)
        self.assertEqual(move.line_ids.filtered(lambda l: l.credit).account_id, self.acc_703)
        self.assertEqual(move.amount_total, 200.0)

    def test_balance_report(self):
        deferral = self._deferral()
        deferral.action_confirm()
        deferral.action_post_due(date(2031, 2, 28))
        self.env.flush_all()
        Report = self.env['l10n_ua.deferral.report']
        rows = Report.search([('deferral_id', '=', deferral.id),
                              ('date', '<=', date(2031, 2, 28))])
        self.assertAlmostEqual(sum(rows.mapped('amount')), 100.0, places=2)
        rows = Report.search([('deferral_id', '=', deferral.id),
                              ('date', '<=', date(2031, 1, 31))])
        self.assertAlmostEqual(sum(rows.mapped('amount')), 200.0, places=2)
        action = self.env['l10n_ua.deferral.balance.wizard'].create(
            {'date': date(2031, 1, 31)}).action_open()
        self.assertIn(('date', '<=', date(2031, 1, 31)), action['domain'])

    # ------------------------------------------------------------------
    # Period closing
    # ------------------------------------------------------------------
    def test_period_closing_posts_idempotently_and_reverses(self):
        deferral = self._deferral()
        deferral.action_confirm()
        feb = deferral.line_ids.filtered(lambda l: l.date == date(2031, 2, 28))
        period = self._period(2031, 2, 28)
        closing = self._closing(period)
        self.assertEqual(closing.deferral_line_ids, feb)

        closing.action_close()
        self.assertEqual(closing.state, 'closed')
        self.assertTrue(feb.is_posted)
        self.assertEqual(feb.closing_id, closing)
        first_move = feb.move_id
        # Only February is recognised by the February closing
        self.assertEqual(len(deferral.line_ids.filtered('is_posted')), 1)
        # The recognised expense is part of the closing (92 → 791)
        closing_92 = closing.closing_line_ids.filtered(
            lambda l: l.account_id == self.acc_92)
        self.assertAlmostEqual(closing_92.balance, 100.0, places=2)
        self.assertAlmostEqual(
            self._balance(self.acc_92, date(2031, 2, 1), date(2031, 2, 28)), 0.0,
            places=2, msg='92 must be closed to 791 for February')

        # Idempotent: posting the period again creates nothing
        self.assertFalse(closing._post_deferral_entries())
        self.assertEqual(feb.move_id, first_move)
        self.assertEqual(self.env['account.move'].search_count(
            [('ref', '=', first_move.ref)]), 1)

        # Reversing the closing reverses the recognition and frees the line
        closing.action_reverse()
        self.assertFalse(feb.move_id)
        self.assertFalse(feb.is_posted)
        self.assertTrue(first_move.reversal_move_ids)
        self.assertAlmostEqual(
            self._balance(self.acc_39, date(2031, 2, 1), date(2031, 2, 28)), 0.0,
            places=2)
        self.assertEqual(deferral.amount_posted, 0.0)

        # Closing again posts exactly one new entry
        closing.action_draft()
        closing.action_close()
        self.assertTrue(feb.is_posted)
        self.assertNotEqual(feb.move_id, first_move)
        self.assertAlmostEqual(
            self._balance(self.acc_39, date(2031, 2, 1), date(2031, 2, 28)), -100.0,
            places=2)

    def test_closing_skips_manually_posted_lines(self):
        deferral = self._deferral()
        deferral.action_confirm()
        deferral.action_post_due(date(2031, 2, 28))
        feb = deferral.line_ids.filtered(lambda l: l.date == date(2031, 2, 28))
        manual_move = feb.move_id
        closing = self._closing(self._period(2031, 2, 28))
        closing.action_close()
        self.assertEqual(feb.move_id, manual_move)
        self.assertFalse(feb.closing_id)
        closing.action_reverse()
        # Not posted by the closing → untouched by its reversal
        self.assertEqual(feb.move_id, manual_move)
        self.assertFalse(manual_move.reversal_move_ids)

    # ------------------------------------------------------------------
    # From invoice lines
    # ------------------------------------------------------------------
    def _bill(self, move_type='in_invoice', account=None, amount=1200.0):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner.id,
            'invoice_date': date(2031, 1, 10),
            'date': date(2031, 1, 10),
            'invoice_line_ids': [(0, 0, {
                'name': 'Страховий поліс на 2031 рік',
                'quantity': 1,
                'price_unit': amount,
                'account_id': (account or self.acc_92).id,
                'tax_ids': [(6, 0, [])],
            })],
        })
        move.action_post()
        return move

    def _wizard(self, move, **vals):
        action = move.action_l10n_ua_defer()
        wizard = self.env['l10n_ua.deferral.create.wizard'].with_context(
            **action['context']).create({
                'date_start': date(2031, 1, 1),
                'date_end': date(2031, 12, 31),
                **vals,
            })
        return wizard

    def test_create_from_vendor_bill(self):
        bill = self._bill()
        wizard = self._wizard(bill)
        line = bill.invoice_line_ids
        self.assertEqual(wizard.move_line_ids, line)
        self.assertEqual(wizard.expense_deferral_account_id, self.acc_39)
        wizard.action_create()

        deferral = line.l10n_ua_deferral_ids
        self.assertEqual(len(deferral), 1)
        self.assertEqual(bill.l10n_ua_deferral_count, 1)
        self.assertEqual(deferral.kind, 'expense')
        self.assertEqual(deferral.state, 'running')
        self.assertEqual(deferral.partner_id, self.partner)
        self.assertEqual(deferral.target_account_id, self.acc_92)
        self.assertEqual(deferral.deferral_account_id, self.acc_39)
        self.assertEqual(deferral.amount_total, 1200.0)
        self.assertEqual(len(deferral.line_ids), 12)
        self.assertEqual(set(deferral.line_ids.mapped('amount')), {100.0})

        # Reclassification 92 → 39 on the bill date
        initial = deferral.initial_move_id
        self.assertEqual(initial.state, 'posted')
        self.assertEqual(initial.date, date(2031, 1, 10))
        self.assertEqual(initial.line_ids.filtered(lambda l: l.debit).account_id, self.acc_39)
        self.assertEqual(initial.line_ids.filtered(lambda l: l.credit).account_id, self.acc_92)
        self.assertAlmostEqual(
            self._balance(self.acc_92, date(2031, 1, 1), date(2031, 1, 10)), 0.0, places=2)

        # The same line cannot be deferred twice
        with self.assertRaises(UserError):
            self._wizard(bill).action_create()

        # Cancelling a schedule without posted lines reverses the reclassification
        deferral.action_cancel()
        self.assertEqual(deferral.state, 'cancelled')
        self.assertTrue(initial.reversal_move_ids)
        self.assertAlmostEqual(
            self._balance(self.acc_39, date(2031, 1, 1), date(2031, 1, 31)), 0.0, places=2)

    def test_create_from_customer_invoice(self):
        invoice = self._bill(move_type='out_invoice', account=self.acc_703, amount=600.0)
        self._wizard(invoice, method='day').action_create()
        deferral = invoice.invoice_line_ids.l10n_ua_deferral_ids
        self.assertEqual(deferral.kind, 'revenue')
        self.assertEqual(deferral.deferral_account_id, self.acc_69)
        self.assertEqual(deferral.target_account_id, self.acc_703)
        self.assertAlmostEqual(sum(deferral.line_ids.mapped('amount')), 600.0, places=2)
        initial = deferral.initial_move_id
        self.assertEqual(initial.line_ids.filtered(lambda l: l.debit).account_id, self.acc_703)
        self.assertEqual(initial.line_ids.filtered(lambda l: l.credit).account_id, self.acc_69)

    def test_create_from_line_booked_on_39(self):
        bill = self._bill(account=self.acc_39)
        with self.assertRaises(UserError):
            self._wizard(bill).action_create()
        self._wizard(bill, target_account_id=self.acc_92.id).action_create()
        deferral = bill.invoice_line_ids.l10n_ua_deferral_ids
        self.assertEqual(deferral.target_account_id, self.acc_92)
        self.assertFalse(deferral.initial_move_id, 'already on 39: no reclassification')
