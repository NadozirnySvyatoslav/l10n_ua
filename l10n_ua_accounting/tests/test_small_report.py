"""Спрощена фінзвітність малого підприємства і мікропідприємства
(НП(С)БО 25, #78). Дати — 2046 рік, рахунки створюються тут."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AccountingTestCase

D = date(2046, 3, 10)

# Rows of the XSD J0901107 / J0901205 (pairs G3/G4), in their order
XSD_SMALL = (
    '1000 1001 1002 1005 1010 1011 1012 1020 1030 1090 1095 1100 1103 1110 1125 1135 1136 '
    '1155 1160 1165 1170 1190 1195 1200 1300 1400 1410 1415 1420 1425 1495 1595 1600 1610 '
    '1615 1620 1621 1625 1630 1665 1690 1695 1700 1900 '
    '2000 2120 2240 2280 2050 2180 2270 2285 2290 2300 2350').split()
XSD_MICRO = (
    '1010 1011 1012 1090 1095 1100 1155 1165 1190 1195 1300 1400 1420 1425 1495 1595 1600 '
    '1615 1620 1625 1630 1690 1695 1900 '
    '2000 2160 2280 2050 2165 2285 2290 2300 2310 2350').split()


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestSmallReport(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_40 = acc('40', 'Зареєстрований капітал', 'equity')
        cls.acc_46 = acc('46', 'Неоплачений капітал', 'equity')
        cls.acc_311 = acc('311', 'Рахунок у банку', 'asset_cash')
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_131 = acc('131', 'Знос основних засобів', 'asset_fixed')
        cls.acc_100 = acc('100', 'Інвестиційна нерухомість', 'asset_fixed')
        cls.acc_26 = acc('26', 'Готова продукція', 'asset_current')
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_631 = acc('631', 'Розрахунки з постачальниками', 'liability_payable', True)
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_732 = acc('732', 'Відсотки одержані', 'income')
        cls.acc_902 = acc('902', 'Собівартість реалізованих товарів', 'expense_direct_cost')
        cls.acc_92 = acc('92', 'Адміністративні витрати', 'expense')

    @classmethod
    def _account(cls, code, name, account_type, reconcile=False):
        Account = cls.env['account.account']
        account = Account.search([
            ('code', '=', code), ('company_ids', 'in', cls.company.id)], limit=1)
        return account or Account.create({
            'code': code, 'name': name, 'account_type': account_type,
            'reconcile': reconcile, 'company_ids': [(6, 0, cls.company.ids)],
        })

    def _entry(self, debit_account, credit_account, amount, on_date=D):
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.misc_journal.id, 'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'partner_id': self.partner.id}),
                (0, 0, {'account_id': credit_account.id, 'credit': amount, 'partner_id': self.partner.id}),
            ],
        })
        move.action_post()

    def _report(self, kind):
        report = self.env['l10n_ua.small.report'].create({
            'kind': kind, 'company_id': self.company.id,
            'date_from': date(2046, 1, 1), 'date_to': date(2046, 12, 31),
        })
        report.action_compute()
        return report

    def _g4(self, report, code, part='balance'):
        return report.line_ids.filtered(lambda l: l.code == code and l.part == part).amount_g4

    def _g3(self, report, code):
        return report.line_ids.filtered(lambda l: l.code == code and l.part == 'pnl').amount_g3

    def _post_year(self):
        self._entry(self.acc_46, self.acc_40, 100000)
        self._entry(self.acc_311, self.acc_46, 60000)
        self._entry(self.acc_104, self.acc_311, 30000)
        self._entry(self.acc_100, self.acc_311, 12000)
        self._entry(self.acc_92, self.acc_131, 3150)
        self._entry(self.acc_26, self.acc_631, 4440)
        self._entry(self.acc_281, self.acc_631, 8000)
        self._entry(self.acc_361, self.acc_702, 25000)
        self._entry(self.acc_902, self.acc_281, 8000)
        self._entry(self.acc_311, self.acc_732, 260)

    def test_rows_follow_the_xsd(self):
        for kind, codes in (('small', XSD_SMALL), ('micro', XSD_MICRO)):
            report = self._report(kind)
            printed = [l.code for l in report.line_ids.sorted(lambda l: (l.part, l.sequence)) if l.code]
            self.assertEqual(printed, codes, kind)

    def test_small_enterprise(self):
        self._post_year()
        report = self._report('small')
        g4 = lambda code: self._g4(report, code)  # noqa: E731
        # Thousands with one decimal; investment property in fixed assets (п. 2.3)
        self.assertEqual(g4('1010'), round((30000 - 3150 + 12000) / 1000, 1))
        self.assertEqual(g4('1012'), -3.2)                      # 3150 → 3.2, in parentheses
        self.assertEqual(g4('1011'), round(g4('1010') - g4('1012'), 1))
        self.assertEqual(g4('1103'), 4.4)                       # готова продукція (26)
        self.assertEqual(g4('1425'), -40.0)
        self.assertEqual(report.balance_difference, 0.0)
        self.assertEqual(g4('1300'), g4('1900'))
        self.assertEqual(self._g3(report, '2000'), 25.0)
        self.assertEqual(self._g3(report, '2240'), 0.3)         # відсотки: інші доходи
        self.assertEqual(self._g3(report, '2180'), 3.2)         # адміністративні
        self.assertEqual(self._g3(report, '2290'), round(25.0 + 0.3 - 8.0 - 3.2, 1))
        values = report._xml_values()
        self.assertEqual(values['R1012G4'], 3.2)                # parentheses: positive
        self.assertEqual(values['R2050G3'], 8.0)

    def test_micro_enterprise(self):
        self._post_year()
        report = self._report('micro')
        self.assertEqual(self._g4(report, '1010'), round((30000 - 3150 + 12000) / 1000, 1))
        self.assertEqual(self._g4(report, '1400'), 100.0)
        self.assertEqual(self._g4(report, '1300'), self._g4(report, '1900'))
        self.assertEqual(self._g3(report, '2160'), 0.3)
        self.assertEqual(self._g3(report, '2165'), 3.2)
        line_2310 = report.line_ids.filtered(lambda l: l.code == '2310')
        line_2310.amount_g3 = 1.5
        self.assertEqual(self._g3(report, '2350'), round(self._g3(report, '2290') - 1.5, 1))
        with self.assertRaises(UserError):
            report.line_ids.filtered(lambda l: l.code == '2000').amount_g3 = 1

    def test_print(self):
        self._post_year()
        report = self._report('micro')
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_small_document', report.ids)[0].decode()
        self.assertIn('Форма № 1-мс', html)
        self.assertIn('(3.2)', html)
