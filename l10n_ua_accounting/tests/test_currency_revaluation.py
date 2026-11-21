"""Тести переоцінки валютних коштів (#141).

Покриття:
- Розрахунок курсової різниці за валютною дебіторкою (курс зріс → дохід)
- Курс впав → втрати
- Проведення формує збалансовану проводку на рахунок доходу/витрат
- Помилка, якщо не налаштовано рахунок результату
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCurrencyRevaluation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Іноземна валюта, відмінна від валюти компанії.
        cls.fx = cls.env.ref('base.USD')
        if cls.fx == cls.company.currency_id:
            cls.fx = cls.env.ref('base.EUR')
        cls.fx.active = True

        Rate = cls.env['res.currency.rate']
        Rate.search([('currency_id', '=', cls.fx.id)]).unlink()
        # rate = одиниць валюти за 1 грн, тобто 1/курс.
        # 1 валюта = 40 грн на дату обліку, 42 грн на дату переоцінки.
        Rate.create({'currency_id': cls.fx.id, 'name': date(2025, 1, 1),
                     'rate': 1.0 / 40.0, 'company_id': cls.company.id})
        Rate.create({'currency_id': cls.fx.id, 'name': date(2025, 6, 30),
                     'rate': 1.0 / 42.0, 'company_id': cls.company.id})

        cls.journal = cls.env['account.journal'].create({
            'name': 'Курс тест', 'code': 'FXJ', 'type': 'general',
            'company_id': cls.company.id})
        cls.acc_recv = cls.env['account.account'].create({
            'name': 'Валютна дебіторка (362)', 'code': 'FXRECV',
            'account_type': 'asset_receivable',
            'company_ids': [(4, cls.company.id)]})
        cls.acc_income = cls.env['account.account'].create({
            'name': 'Дохід', 'code': 'FXINC', 'account_type': 'income',
            'company_ids': [(4, cls.company.id)]})
        cls.acc_gain = cls.env['account.account'].create({
            'name': '714', 'code': 'FX714', 'account_type': 'income_other',
            'company_ids': [(4, cls.company.id)]})
        cls.acc_loss = cls.env['account.account'].create({
            'name': '945', 'code': 'FX945', 'account_type': 'expense',
            'company_ids': [(4, cls.company.id)]})
        cls.company.write({
            'l10n_ua_fx_gain_op_account_id': cls.acc_gain.id,
            'l10n_ua_fx_loss_op_account_id': cls.acc_loss.id,
        })

    def _book_receivable(self, fc_amount, uah_amount):
        """Валютна дебіторка: Дт 362 (fc/uah) / Кт дохід (uah), дата 2025-01-01."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date(2025, 1, 1),
            'line_ids': [
                (0, 0, {'account_id': self.acc_recv.id,
                        'debit': uah_amount, 'credit': 0.0,
                        'amount_currency': fc_amount, 'currency_id': self.fx.id}),
                (0, 0, {'account_id': self.acc_income.id,
                        'debit': 0.0, 'credit': uah_amount,
                        'amount_currency': -uah_amount,
                        'currency_id': self.company.currency_id.id}),
            ],
        })
        move.action_post()
        return move

    def _reval(self):
        return self.env['l10n_ua.currency.revaluation'].create({
            'date': date(2025, 6, 30),
            'journal_id': self.journal.id,
            'company_id': self.company.id,
        })

    def test_gain_on_rising_rate(self):
        # 100 валюти обліковано за 4000 грн; на 30.06 курс 42 → 4200; +200 дохід.
        self._book_receivable(100.0, 4000.0)
        reval = self._reval()
        reval.action_compute()

        line = reval.line_ids.filtered(lambda l: l.account_id == self.acc_recv)
        self.assertEqual(len(line), 1)
        self.assertAlmostEqual(line.fc_balance, 100.0)
        self.assertAlmostEqual(line.book_balance, 4000.0)
        self.assertAlmostEqual(line.revalued_balance, 4200.0)
        self.assertAlmostEqual(line.fx_difference, 200.0)
        self.assertAlmostEqual(reval.total_gain, 200.0)

        reval.action_post()
        self.assertEqual(reval.state, 'posted')
        move = reval.move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        # Проводка збалансована; дохід 714 отримав кредит 200.
        self.assertAlmostEqual(sum(move.line_ids.mapped('debit')),
                               sum(move.line_ids.mapped('credit')))
        gain_line = move.line_ids.filtered(lambda l: l.account_id == self.acc_gain)
        self.assertAlmostEqual(gain_line.credit, 200.0)
        recv_line = move.line_ids.filtered(lambda l: l.account_id == self.acc_recv)
        self.assertAlmostEqual(recv_line.debit, 200.0)

    def test_loss_on_falling_rate(self):
        # Знизимо курс переоцінки до 38 → 100×38=3800; 3800-4000 = -200 втрати.
        self.env['res.currency.rate'].search([
            ('currency_id', '=', self.fx.id), ('name', '=', date(2025, 6, 30)),
        ]).rate = 1.0 / 38.0
        self._book_receivable(100.0, 4000.0)
        reval = self._reval()
        reval.action_compute()

        line = reval.line_ids.filtered(lambda l: l.account_id == self.acc_recv)
        self.assertAlmostEqual(line.fx_difference, -200.0)
        self.assertAlmostEqual(reval.total_loss, 200.0)

        reval.action_post()
        loss_line = reval.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_loss)
        self.assertAlmostEqual(loss_line.debit, 200.0)

    def test_missing_account_raises(self):
        self.company.l10n_ua_fx_gain_op_account_id = False
        self._book_receivable(100.0, 4000.0)
        reval = self._reval()
        reval.action_compute()
        with self.assertRaises(UserError):
            reval.action_post()

    def test_second_revaluation_uses_previous_one(self):
        """#624: друга переоцінка рахує різницю від попередньої, а не від
        дати обліку."""
        Rate = self.env['res.currency.rate']
        Rate.create({'currency_id': self.fx.id, 'name': date(2025, 9, 30),
                     'rate': 1.0 / 43.5, 'company_id': self.company.id})
        self._book_receivable(100.0, 4000.0)

        first = self._reval()
        first.action_compute()
        self.assertAlmostEqual(first.total_gain, 200.0)
        first.action_post()

        second = self.env['l10n_ua.currency.revaluation'].create({
            'date': date(2025, 9, 30),
            'journal_id': self.journal.id,
            'company_id': self.company.id,
        })
        second.action_compute()
        line = second.line_ids.filtered(lambda l: l.account_id == self.acc_recv)
        self.assertEqual(len(line), 1)
        # Балансова вартість = 4000 + 200 (перша переоцінка) = 4200;
        # 100 × 43.5 = 4350 → різниця 150, а не 350.
        self.assertAlmostEqual(line.book_balance, 4200.0)
        self.assertAlmostEqual(line.revalued_balance, 4350.0)
        self.assertAlmostEqual(line.fx_difference, 150.0)
        second.action_post()

        # Після двох переоцінок залишок рахунку в гривні = валюта × курс.
        recv_balance = sum(self.env['account.move.line'].search([
            ('account_id', '=', self.acc_recv.id),
            ('parent_state', '=', 'posted'),
        ]).mapped('balance'))
        self.assertAlmostEqual(recv_balance, 4350.0)

        # Повторна переоцінка на ту саму дату різниць не дає.
        third = self.env['l10n_ua.currency.revaluation'].create({
            'date': date(2025, 9, 30),
            'journal_id': self.journal.id,
            'company_id': self.company.id,
        })
        third.action_compute()
        self.assertFalse(third.line_ids)

    def test_cancelled_revaluation_is_ignored(self):
        """#624: скасована (повернена в чернетку) переоцінка не впливає на базу."""
        self._book_receivable(100.0, 4000.0)
        first = self._reval()
        first.action_compute()
        first.action_post()
        first.action_draft()

        second = self._reval()
        second.action_compute()
        self.assertAlmostEqual(second.total_gain, 200.0)
