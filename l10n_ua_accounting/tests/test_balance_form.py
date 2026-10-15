"""Форма 1 (баланс): суми зі знаком і розгорнуте сальдо розрахунків — issue #386.

Рахунки створюються тут, тож тест не залежить від плану рахунків бази.
"""

from datetime import date

from odoo.tests import tagged

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestBalanceForm(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_40 = acc('40', 'Зареєстрований капітал', 'equity')
        cls.acc_301 = acc('301', 'Готівка', 'asset_cash')
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_131 = acc('131', 'Знос основних засобів', 'asset_fixed')
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_631 = acc('631', 'Розрахунки з постачальниками', 'liability_payable', True)
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')
        cls.acc_499 = acc('499', 'Рахунок без рядка форми', 'equity')
        Partner = cls.env['res.partner']
        cls.supplier_a = Partner.create({'name': 'Постачальник А'})
        cls.supplier_b = Partner.create({'name': 'Постачальник Б'})
        cls.customer_c = Partner.create({'name': 'Покупець В'})
        cls.customer_d = Partner.create({'name': 'Покупець Г'})

    @classmethod
    def _account(cls, code, name, account_type, reconcile=False):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'reconcile': reconcile,
            'company_ids': [(6, 0, cls.company.ids)],
        })

    def _entry(self, on_date, *lines):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': account.id, 'partner_id': partner.id if partner else False,
                        'debit': debit, 'credit': credit})
                for account, partner, debit, credit in lines
            ],
        })
        move.action_post()
        return move

    def _report(self, on_date):
        report = self.env['l10n_ua.balance.report'].create({
            'date_to': on_date,
            'comparison_date': date(2039, 12, 31),
            'company_id': self.company.id,
        })
        report.action_compute()
        return report

    def _row(self, report, code):
        """Change of the row since the comparison date: the database may hold
        entries of its own before the dates used here."""
        line = report.line_ids.filtered(lambda l: l.code == code)
        return line.current_amount - line.previous_amount

    def test_balance_balances_with_split_settlements(self):
        d = date(2040, 3, 15)
        self._entry(d, (self.acc_301, None, 10000, 0), (self.acc_104, None, 2000, 0),
                    (self.acc_40, None, 0, 12000))
        # Goods bought on credit from A; an advance paid to B
        self._entry(d, (self.acc_281, None, 1000, 0), (self.acc_631, self.supplier_a, 0, 1000))
        self._entry(d, (self.acc_631, self.supplier_b, 500, 0), (self.acc_301, None, 0, 500))
        # Goods sold on credit to C; an advance received from D
        self._entry(d, (self.acc_361, self.customer_c, 1200, 0), (self.acc_702, None, 0, 1200))
        self._entry(d, (self.acc_301, None, 300, 0), (self.acc_361, self.customer_d, 0, 300))
        # Depreciation, period not closed yet
        self._entry(d, (self.acc_92, None, 200, 0), (self.acc_131, None, 0, 200))

        report = self._report(date(2040, 3, 31))
        self.assertAlmostEqual(self._row(report, '1300'), self._row(report, '1900'), places=2)
        # 9800 cash + 1800 fixed + 1000 goods + 500 advance paid + 1200 receivable
        self.assertAlmostEqual(self._row(report, '1300'), 14300.0, places=2)
        self.assertNotIn('499', report.unmapped_accounts or '')
        # Fixed assets net of depreciation
        self.assertAlmostEqual(self._row(report, '1010'), 1800.0, places=2)
        # Supplier settlements: advance paid is an asset, debt a liability
        self.assertAlmostEqual(self._row(report, '1130'), 500.0, places=2)
        self.assertAlmostEqual(self._row(report, '1615'), 1000.0, places=2)
        # Customer settlements: debt is an asset, advance received a liability
        self.assertAlmostEqual(self._row(report, '1125'), 1200.0, places=2)
        self.assertAlmostEqual(self._row(report, '1635'), 300.0, places=2)
        # Unclosed result (1200 − 200) is in retained earnings with a plus sign
        self.assertAlmostEqual(self._row(report, '1420'), 1000.0, places=2)
        self.assertAlmostEqual(self._row(report, '1400'), 12000.0, places=2)
        self.assertAlmostEqual(self._row(report, '1165'), 9800.0, places=2)

    def test_unmapped_account_is_reported(self):
        d = date(2041, 3, 15)
        self._entry(d, (self.acc_301, None, 700, 0), (self.acc_499, None, 0, 700))
        report = self._report(date(2041, 3, 31))
        self.assertIn('499', report.unmapped_accounts)
