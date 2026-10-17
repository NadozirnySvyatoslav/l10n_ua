"""Форма 1 (баланс): суми зі знаком і розгорнуте сальдо розрахунків — issue #386;
рядки і рахунки за Додатком 1 до НП(С)БО 1 — issue #422.

Рахунки створюються тут, тож тест не залежить від плану рахунків бази.
"""

from datetime import date

from odoo.tests import tagged

from odoo.addons.l10n_ua_accounting.models.l10n_ua_balance_report import (
    BALANCE_ADDITIONAL_CODES,
)

from .common import AccountingTestCase


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestBalanceForm(AccountingTestCase):

    # Codes of Додаток 1 to НП(С)БО 1, in the order of the form
    OFFICIAL_CODES = [
        '1000', '1001', '1002', '1005', '1010', '1011', '1012', '1015', '1020',
        '1030', '1035', '1040', '1045', '1090', '1095',
        '1100', '1110', '1125', '1130', '1135', '1136', '1155', '1160', '1165',
        '1170', '1190', '1195', '1200', '1300',
        '1400', '1405', '1410', '1415', '1420', '1425', '1430', '1495',
        '1500', '1510', '1515', '1520', '1525', '1595',
        '1600', '1610', '1615', '1620', '1621', '1625', '1630', '1660', '1665',
        '1690', '1695', '1700', '1900',
    ]
    SUB_CODES = ['1001', '1002', '1011', '1012', '1136', '1621']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_40 = acc('40', 'Зареєстрований капітал', 'equity')
        cls.acc_301 = acc('301', 'Готівка', 'asset_cash')
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_100 = acc('100', 'Інвестиційна нерухомість', 'asset_fixed')
        cls.acc_131 = acc('131', 'Знос основних засобів', 'asset_fixed')
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_631 = acc('631', 'Розрахунки з постачальниками', 'liability_payable', True)
        cls.acc_641 = acc('641', 'Розрахунки за податками', 'liability_current')
        cls.acc_643 = acc('643', "Податкові зобов'язання", 'liability_current')
        cls.acc_644 = acc('644', 'Податковий кредит', 'asset_current')
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')
        cls.acc_499 = acc('499', 'Рахунок без рядка форми', 'equity')
        # #422
        cls.acc_41 = acc('41', 'Капітал у дооцінках', 'equity')
        cls.acc_42 = acc('42', 'Додатковий капітал', 'equity')
        cls.acc_54 = acc('54', "Відстрочені податкові зобов'язання", 'liability_non_current')
        cls.acc_55 = acc('55', "Інші довгострокові зобов'язання", 'liability_non_current')
        cls.acc_501 = acc('501', 'Довгострокові кредити банків', 'liability_non_current')
        cls.acc_505 = acc('505', 'Інші довгострокові позики', 'liability_non_current')
        cls.acc_12 = acc('12', 'Нематеріальні активи', 'asset_non_current')
        cls.acc_133 = acc('133', 'Накопичена амортизація НМА', 'asset_non_current')
        cls.acc_141 = acc('141', 'Інвестиції за методом участі в капіталі', 'asset_non_current')
        cls.acc_143 = acc('143', "Інвестиції непов'язаним сторонам", 'asset_non_current')
        cls.acc_183 = acc('183', 'Інша дебіторська заборгованість', 'asset_non_current')
        cls.acc_184 = acc('184', 'Інші необоротні активи', 'asset_non_current')
        cls.acc_211 = acc('211', 'Поточні біологічні активи рослинництва', 'asset_current')
        cls.acc_286 = acc('286', 'Необоротні активи, утримувані для продажу', 'asset_current')
        cls.acc_621 = acc('621', 'Короткострокові векселі видані', 'liability_current')
        cls.acc_680 = acc('680', 'Розрахунки, пов’язані з необоротними активами для продажу',
                          'liability_current')
        cls.acc_6413 = acc('6413', 'Розрахунки за податком на прибуток', 'liability_current')
        cls.acc_981 = acc('981', 'Податок на прибуток від звичайної діяльності', 'expense')
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

    def test_vat_643_644_balance(self):
        d = date(2042, 3, 15)
        self._entry(d, (self.acc_301, None, 12000, 0), (self.acc_40, None, 0, 12000))
        # Advance received 1200: ПДВ 200 accrued to 643 on the first event
        self._entry(d, (self.acc_301, None, 1200, 0), (self.acc_361, self.customer_d, 0, 1200))
        self._entry(d, (self.acc_643, None, 200, 0), (self.acc_641, None, 0, 200))
        # Advance paid 600: ПДВ 100 of tax credit waits on 644
        self._entry(d, (self.acc_631, self.supplier_b, 600, 0), (self.acc_301, None, 0, 600))
        self._entry(d, (self.acc_641, None, 100, 0), (self.acc_644, None, 0, 100))
        report = self._report(date(2042, 3, 31))
        self.assertNotIn('643', report.unmapped_accounts or '')
        self.assertNotIn('644', report.unmapped_accounts or '')
        self.assertAlmostEqual(self._row(report, '1300'), self._row(report, '1900'), places=2)
        # Debit balance of 643 is another current asset, credit balance of
        # 644 another current liability; 641 nets to a debt of 100
        self.assertAlmostEqual(self._row(report, '1190'), 200.0, places=2)
        self.assertAlmostEqual(self._row(report, '1690'), 100.0, places=2)
        self.assertAlmostEqual(self._row(report, '1620'), 100.0, places=2)
        self.assertAlmostEqual(self._row(report, '1300'), 13400.0, places=2)
        self.assertAlmostEqual(self._row(report, '1195'), 13400.0, places=2)

    def test_drill_down_follows_row_assignment(self):
        d = date(2043, 3, 15)
        self._entry(d, (self.acc_104, None, 2000, 0), (self.acc_100, None, 500, 0),
                    (self.acc_40, None, 0, 2500))
        sale = self._entry(d, (self.acc_361, self.customer_c, 1200, 0),
                           (self.acc_702, None, 0, 1200))
        advance = self._entry(d, (self.acc_301, None, 300, 0),
                              (self.acc_361, self.customer_d, 0, 300))
        report = self._report(date(2043, 3, 31))

        def drill(code):
            line = report.line_ids.filtered(lambda l: l.code == code)
            action = line.action_view_move_lines()
            return self.env['account.move.line'].search(action['domain'])

        lines_1010 = drill('1010')
        self.assertIn(self.acc_104, lines_1010.account_id)
        self.assertNotIn(self.acc_100, lines_1010.account_id)
        self.assertIn(self.acc_100, drill('1015').account_id)
        sale_line = sale.line_ids.filtered(lambda l: l.account_id == self.acc_361)
        advance_line = advance.line_ids.filtered(lambda l: l.account_id == self.acc_361)
        lines_1125 = drill('1125')
        self.assertIn(sale_line, lines_1125)
        self.assertNotIn(advance_line, lines_1125)
        lines_1635 = drill('1635')
        self.assertIn(advance_line, lines_1635)
        self.assertNotIn(sale_line, lines_1635)

    # ── Рядки форми за Додатком 1 до НП(С)БО 1 (ред. від 23.12.2025), #422 ──

    def _line(self, report, code):
        return report.line_ids.filtered(lambda l: l.code == code)

    def _assert_balanced(self, report):
        self.assertAlmostEqual(self._row(report, '1300'), self._row(report, '1900'), places=2)

    def test_rows_of_official_form(self):
        report = self._report(date(2044, 3, 31))
        codes = [c for c in report.line_ids.sorted('sequence').mapped('code')
                 if c and c not in BALANCE_ADDITIONAL_CODES]
        self.assertEqual(codes, self.OFFICIAL_CODES)
        for code in self.SUB_CODES:
            self.assertEqual(self._line(report, code).line_type, 'sub', code)
        for code in ('1030', '1035', '1090', '1110', '1405', '1500', '1520'):
            self.assertEqual(self._line(report, code).line_type, 'detail', code)

    def test_additional_article_shown_with_amount(self):
        """1605 «Векселі видані» (додаток 3) is in the total and printed only
        when it holds an amount."""
        d = date(2045, 3, 15)
        self._entry(d, (self.acc_281, None, 400, 0), (self.acc_621, None, 0, 400))
        report = self._report(date(2045, 3, 31))
        self.assertAlmostEqual(self._row(report, '1605'), 400.0, places=2)
        self.assertAlmostEqual(self._row(report, '1695'), 400.0, places=2)
        self.assertNotIn('1120', report.line_ids.mapped('code'))
        self._assert_balanced(report)

    def test_revaluation_and_deferred_tax(self):
        d = date(2046, 3, 15)
        self._entry(d, (self.acc_301, None, 5000, 0), (self.acc_40, None, 0, 4000),
                    (self.acc_42, None, 0, 1000))
        # Revaluation of a fixed asset and the deferred tax on it
        self._entry(d, (self.acc_104, None, 1000, 0), (self.acc_41, None, 0, 1000))
        self._entry(d, (self.acc_41, None, 180, 0), (self.acc_54, None, 0, 180))
        report = self._report(date(2046, 3, 31))
        self.assertAlmostEqual(self._row(report, '1405'), 820.0, places=2)
        self.assertAlmostEqual(self._row(report, '1410'), 1000.0, places=2)
        self.assertAlmostEqual(self._row(report, '1500'), 180.0, places=2)
        self.assertAlmostEqual(self._row(report, '1515'), 0.0, places=2)
        self.assertAlmostEqual(self._row(report, '1495'), 5820.0, places=2)
        self.assertAlmostEqual(self._row(report, '1595'), 180.0, places=2)
        self.assertAlmostEqual(self._row(report, '1300'), 6000.0, places=2)
        self._assert_balanced(report)

    def test_components_not_double_counted(self):
        d = date(2047, 3, 15)
        self._entry(d, (self.acc_12, None, 1000, 0), (self.acc_104, None, 2000, 0),
                    (self.acc_301, None, 50, 0), (self.acc_40, None, 0, 3050))
        self._entry(d, (self.acc_92, None, 800, 0), (self.acc_133, None, 0, 300),
                    (self.acc_131, None, 0, 500))
        # Income tax overpaid
        self._entry(d, (self.acc_6413, None, 50, 0), (self.acc_301, None, 0, 50))
        report = self._report(date(2047, 3, 31))
        self.assertAlmostEqual(self._row(report, '1001'), 1000.0, places=2)
        self.assertAlmostEqual(self._row(report, '1002'), -300.0, places=2)
        self.assertAlmostEqual(self._row(report, '1000'), 700.0, places=2)
        self.assertAlmostEqual(self._row(report, '1011'), 2000.0, places=2)
        self.assertAlmostEqual(self._row(report, '1012'), -500.0, places=2)
        self.assertAlmostEqual(self._row(report, '1010'), 1500.0, places=2)
        self.assertAlmostEqual(self._row(report, '1095'), 2200.0, places=2)
        self.assertAlmostEqual(self._row(report, '1135'), 50.0, places=2)
        self.assertAlmostEqual(self._row(report, '1136'), 50.0, places=2)
        self.assertAlmostEqual(self._row(report, '1621'), 0.0, places=2)
        self.assertAlmostEqual(self._row(report, '1195'), 50.0, places=2)
        self.assertAlmostEqual(self._row(report, '1300'), 2250.0, places=2)
        self._assert_balanced(report)
        # Drill-down of a component shows only its own accounts
        action = self._line(report, '1012').action_view_move_lines()
        accounts = self.env['account.move.line'].search(action['domain']).account_id
        self.assertIn(self.acc_131, accounts)
        self.assertNotIn(self.acc_104, accounts)
        self.assertNotIn(self.acc_133, accounts)

    def test_profit_tax_payable_including_row(self):
        d = date(2048, 3, 15)
        self._entry(d, (self.acc_301, None, 1000, 0), (self.acc_40, None, 0, 1000))
        self._entry(d, (self.acc_981, None, 80, 0), (self.acc_6413, None, 0, 80))
        self._entry(d, (self.acc_92, None, 20, 0), (self.acc_641, None, 0, 20))
        report = self._report(date(2048, 3, 31))
        self.assertAlmostEqual(self._row(report, '1620'), 100.0, places=2)
        self.assertAlmostEqual(self._row(report, '1621'), 80.0, places=2)
        self.assertAlmostEqual(self._row(report, '1136'), 0.0, places=2)
        self.assertAlmostEqual(self._row(report, '1695'), 100.0, places=2)
        self._assert_balanced(report)

    def test_accounts_of_new_rows(self):
        d = date(2049, 3, 15)
        self._entry(d, (self.acc_141, None, 100, 0), (self.acc_143, None, 200, 0),
                    (self.acc_183, None, 300, 0), (self.acc_184, None, 400, 0),
                    (self.acc_211, None, 500, 0), (self.acc_281, None, 600, 0),
                    (self.acc_286, None, 700, 0),
                    (self.acc_40, None, 0, 1800), (self.acc_501, None, 0, 300),
                    (self.acc_505, None, 0, 200), (self.acc_55, None, 0, 100),
                    (self.acc_680, None, 0, 400))
        report = self._report(date(2049, 3, 31))
        expected = {
            '1030': 100, '1035': 200, '1040': 300, '1090': 400, '1095': 1000,
            '1110': 500, '1100': 600, '1195': 1100, '1200': 700, '1300': 2800,
            '1510': 300, '1515': 300, '1595': 600, '1700': 400, '1695': 0,
            '1900': 2800,
        }
        for code, amount in expected.items():
            self.assertAlmostEqual(self._row(report, code), amount, places=2, msg=code)
        for code in ('141', '143', '183', '184', '211', '286', '505', '680'):
            self.assertNotIn(code, report.unmapped_accounts or '')
