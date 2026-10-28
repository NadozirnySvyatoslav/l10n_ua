"""Списання торговельної націнки за середнім відсотком (НП(С)БО 9, п. 22) — #148.

Приклад, на якому стоять тести:
  грудень — надійшло товарів на 10 000 за продажними цінами (собівартість
            6 000, націнка 4 000);
  січень  — надійшло ще на 5 000 (3 000 + 2 000), продано на 6 000,
            нестача на 1 500 (за продажними цінами).
Середній % = (4 000 + 2 000) / (10 000 + 5 000) = 40 %; націнка на вибуле
7 500 × 40 % = 3 000: 2 400 на 902 і 600 на 947.
"""
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestTradeMarkup(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_282 = cls._account('282', 'Товари в торгівлі', 'asset_current')
        cls.acc_285 = cls._account('285', 'Торгова націнка', 'asset_current')
        cls.acc_631 = cls._account('631', 'Розрахунки з постачальниками', 'liability_payable')
        cls.acc_902 = cls._account('902', 'Собівартість реалізованих товарів', 'expense_direct_cost')
        cls.acc_947 = cls._account('947', 'Нестачі і втрати від псування цінностей', 'expense')
        cls.acc_791 = cls._account('791', 'Результат операційної діяльності', 'equity')
        cls.acc_792 = cls._account('792', 'Результат фінансових операцій', 'equity')
        cls.acc_793 = cls._account('793', 'Результат іншої діяльності', 'equity')
        cls.acc_441 = cls._account('4411', 'Нерозподілений прибуток', 'equity')
        cls.acc_442 = cls._account('4421', 'Непокриті збитки', 'equity')
        cls.company.fiscalyear_lock_date = False

        cls._receipt(date(2025, 12, 10), cost=6000.0, markup=4000.0)
        cls._receipt(date(2026, 1, 12), cost=3000.0, markup=2000.0)
        cls._disposal(date(2026, 1, 20), cls.acc_902, 6000.0)
        cls._disposal(date(2026, 1, 25), cls.acc_947, 1500.0)

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

    @classmethod
    def _post(cls, on_date, lines):
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': cls.misc_journal.id,
            'date': on_date,
            'line_ids': [(0, 0, vals) for vals in lines],
        })
        move.action_post()
        return move

    @classmethod
    def _receipt(cls, on_date, cost, markup):
        """Надходження: Дт 282 (роздрібна вартість) Кт 631 (собівартість), Кт 285."""
        return cls._post(on_date, [
            {'account_id': cls.acc_282.id, 'debit': cost + markup},
            {'account_id': cls.acc_631.id, 'credit': cost, 'partner_id': cls.partner.id},
            {'account_id': cls.acc_285.id, 'credit': markup},
        ])

    @classmethod
    def _disposal(cls, on_date, account, retail):
        """Вибуття за продажними цінами: Дт 902 / 947 Кт 282."""
        return cls._post(on_date, [
            {'account_id': account.id, 'debit': retail},
            {'account_id': cls.acc_282.id, 'credit': retail},
        ])

    def _markup(self, date_from, date_to):
        return self.env['l10n_ua.trade.markup'].create({
            'company_id': self.company.id,
            'date_from': date_from,
            'date_to': date_to,
            'journal_id': self.misc_journal.id,
        })

    def _balance(self, account, date_to):
        groups = self.env['account.move.line']._read_group([
            ('account_id', '=', account.id), ('parent_state', '=', 'posted'),
            ('date', '<=', date_to)], [], ['balance:sum'])
        return groups[0][0] or 0.0

    def test_default_accounts(self):
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup._set_default_accounts()
        self.assertEqual(markup.goods_account_id, self.acc_282)
        self.assertEqual(markup.markup_account_id, self.acc_285)
        self.assertEqual(markup.default_account_id, self.acc_902)

    def test_average_percent(self):
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup.action_compute()
        self.assertAlmostEqual(markup.opening_retail, 10000.0)
        self.assertAlmostEqual(markup.received_retail, 5000.0)
        self.assertAlmostEqual(markup.opening_markup, 4000.0)
        self.assertAlmostEqual(markup.received_markup, 2000.0)
        self.assertAlmostEqual(markup.disposed_retail, 7500.0)
        self.assertAlmostEqual(markup.markup_percent, 40.0)
        self.assertAlmostEqual(markup.markup_amount, 3000.0)

    def test_split_by_disposal_account(self):
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup.action_compute()
        split = {line.account_id: line.markup_amount for line in markup.line_ids}
        self.assertEqual(split, {self.acc_902: 2400.0, self.acc_947: 600.0})

    def test_post_entry_and_cost_of_sales(self):
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup.action_post()
        self.assertEqual(markup.state, 'posted')
        move = markup.move_id
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.date, date(2026, 1, 31))
        debit_285 = sum(move.line_ids.filtered(
            lambda l: l.account_id == self.acc_285).mapped('debit'))
        self.assertAlmostEqual(debit_285, 3000.0)
        # Собівартість проданого = продажна вартість − націнка = 6 000 − 2 400.
        self.assertAlmostEqual(self._balance(self.acc_902, date(2026, 1, 31)), 3600.0)
        # Залишок 285 відповідає націнці на залишок товарів: 7 500 × 40 %.
        self.assertAlmostEqual(-self._balance(self.acc_285, date(2026, 1, 31)), 3000.0)

    def test_next_month_uses_balance_after_write_off(self):
        self._markup(date(2026, 1, 1), date(2026, 1, 31)).action_post()
        self._disposal(date(2026, 2, 5), self.acc_902, 2500.0)
        february = self._markup(date(2026, 2, 1), date(2026, 2, 28))
        february.action_compute()
        self.assertAlmostEqual(february.opening_retail, 7500.0)
        self.assertAlmostEqual(february.opening_markup, 3000.0)
        self.assertAlmostEqual(february.markup_percent, 40.0)
        self.assertAlmostEqual(february.markup_amount, 1000.0)

    def test_rounding_goes_to_total(self):
        """Розщеплення за рахунками в сумі дає рівно вибуле × середній %."""
        self._disposal(date(2026, 1, 26), self.acc_947, 0.01)
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup.action_compute()
        self.assertAlmostEqual(sum(markup.line_ids.mapped('markup_amount')),
                               markup.markup_amount)

    def test_overlap_refused(self):
        self._markup(date(2026, 1, 1), date(2026, 1, 31)).action_post()
        with self.assertRaises(UserError):
            self._markup(date(2026, 1, 15), date(2026, 1, 31)).action_post()

    def test_cancel_reverses(self):
        markup = self._markup(date(2026, 1, 1), date(2026, 1, 31))
        markup.action_post()
        markup.action_cancel()
        self.assertEqual(markup.state, 'cancelled')
        self.assertAlmostEqual(self._balance(self.acc_902, date(2026, 1, 31)), 6000.0)
        markup.action_draft()
        self.assertEqual(markup.state, 'draft')
        self.assertFalse(markup.move_id)

    def test_period_closing_posts_and_reverses(self):
        period = self.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(2026, 1, 1),
            'date_end': date(2026, 1, 31),
            'company_id': self.company.id,
        })
        closing = self.env['l10n_ua.period.closing'].create({
            'period_id': period.id,
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
            'account_791_id': self.acc_791.id,
            'account_792_id': self.acc_792.id,
            'account_793_id': self.acc_793.id,
            'account_profit_id': self.acc_441.id,
            'account_loss_id': self.acc_442.id,
            'lock_period': False,
        })
        closing.action_close()
        markup = self.env['l10n_ua.trade.markup'].search([('closing_id', '=', closing.id)])
        self.assertEqual(markup.state, 'posted')
        self.assertAlmostEqual(markup.markup_amount, 3000.0)

        closing.action_reverse()
        self.assertEqual(markup.state, 'cancelled')

    def test_company_without_retail_untouched(self):
        """Нема обороту 282 — закриття нічого не створює."""
        period = self.env['l10n_ua.tax.period'].create({
            'period_type': 'month',
            'date_start': date(2026, 3, 1),
            'date_end': date(2026, 3, 31),
            'company_id': self.company.id,
        })
        closing = self.env['l10n_ua.period.closing'].create({
            'period_id': period.id,
            'company_id': self.company.id,
            'journal_id': self.misc_journal.id,
        })
        closing._post_trade_markup()
        self.assertFalse(self.env['l10n_ua.trade.markup'].search([
            ('company_id', '=', self.company.id),
            ('date_to', '=', date(2026, 3, 31)),
        ]))
