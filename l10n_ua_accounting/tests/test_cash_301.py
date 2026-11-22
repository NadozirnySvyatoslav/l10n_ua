"""ПКО/ВКО проводяться по рахунку каси 301, а не через 311 (#598).

Компанія — на плані ua_psbo, як у пілота: саме там рахунки неоплачених
надходжень/платежів ядра лягають на 311 (банк).
"""
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCashOrders301(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'ТОВ Каса 301 Тест',
            'country_id': cls.env.ref('base.ua').id,
        })
        cls.env['account.chart.template'].try_loading(
            'ua_psbo', company=cls.company, install_demo=False)
        cls.env.user.company_ids |= cls.company
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=cls.company.ids))
        cls.cash = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'cash'),
        ], limit=1)
        cls.bank = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id), ('type', '=', 'bank'),
        ], limit=1)
        cls.partner = cls.env['res.partner'].create({'name': 'Покупець 301'})
        cls.acc_301 = cls.cash.default_account_id

    def _pay(self, journal, payment_type, amount, day):
        payment = self.env['account.payment'].create({
            'payment_type': payment_type,
            'partner_type': 'customer' if payment_type == 'inbound' else 'supplier',
            'partner_id': self.partner.id,
            'amount': amount,
            'date': day,
            'journal_id': journal.id,
        })
        payment.action_post()
        return payment

    def test_cash_journal_is_301(self):
        self.assertTrue(self.cash, 'шаблон ua_psbo має створити журнал каси')
        self.assertTrue(self.acc_301.code.startswith('301'))

    def test_pko_debits_301(self):
        """ПКО: Дт 301 Кт 361, платіж одразу оплачений."""
        pko = self._pay(self.cash, 'inbound', 5000.0, date(2026, 11, 10))
        liquidity = pko.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_301)
        self.assertEqual(liquidity.debit, 5000.0)
        counterpart = pko.move_id.line_ids - liquidity
        self.assertTrue(counterpart.account_id.code.startswith('361'))
        self.assertFalse(pko.move_id.line_ids.filtered(
            lambda l: l.account_id.code.startswith('311')), 'каса не йде через 311')
        self.assertEqual(pko.state, 'paid')

    def test_vko_credits_301_and_balance(self):
        """ВКО: Кт 301; залишок каси для ліміту — 301."""
        self._pay(self.cash, 'inbound', 5000.0, date(2026, 11, 10))
        vko = self._pay(self.cash, 'outbound', 2000.0, date(2026, 11, 10))
        liquidity = vko.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_301)
        self.assertEqual(liquidity.credit, 2000.0)
        self.assertAlmostEqual(self.cash._get_cash_balance(), 3000.0)

    def test_cash_book_next_day_opening(self):
        """Касова книга 11.11 відкривається залишком 10.11."""
        self._pay(self.cash, 'inbound', 5000.0, date(2026, 11, 10))
        wizard = self.env['l10n_ua.cash.book.wizard'].create({
            'journal_id': self.cash.id,
            'company_id': self.company.id,
            'date_from': date(2026, 11, 11),
            'date_to': date(2026, 11, 11),
        })
        self.assertAlmostEqual(wizard._get_opening_balance(self.acc_301), 5000.0)

    def test_cash_limit_warning(self):
        self.company.write({
            'l10n_ua_cash_limit_enabled': True,
            'l10n_ua_cash_limit': 1000.0,
        })
        pko = self._pay(self.cash, 'inbound', 5000.0, date(2026, 11, 10))
        self.assertTrue(pko.message_ids.filtered(lambda m: 'ліміт' in (m.body or '')))

    def test_explicit_method_account_wins(self):
        """Рахунок, вказаний у способі оплати журналу каси, не переписується."""
        own = self.env['account.account'].create({
            'name': 'Транзит каси (свій)',
            'code': '333901',
            'account_type': 'asset_current',
            'reconcile': True,
            'company_ids': [(4, self.company.id)],
        })
        self.cash.inbound_payment_method_line_ids.payment_account_id = own
        pko = self._pay(self.cash, 'inbound', 100.0, date(2026, 11, 10))
        self.assertEqual(pko.outstanding_account_id, own)

    def test_bank_unchanged(self):
        """Банківський платіж як і раніше — через рахунок неоплачених надходжень."""
        payment = self._pay(self.bank, 'inbound', 100.0, date(2026, 11, 10))
        self.assertNotEqual(payment.outstanding_account_id, self.bank.default_account_id)
