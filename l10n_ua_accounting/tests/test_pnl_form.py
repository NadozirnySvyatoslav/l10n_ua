"""Форма № 2 за Додатком 1 до НП(С)БО 1 (#78): чисті обороти без закриття
через 79, пари «прибуток/збиток», розділи II–IV.

Рахунки створюються тут, дати — 2043 рік.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AccountingTestCase

D = date(2043, 4, 10)


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestPnlForm(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_281 = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_201 = acc('201', 'Сировина й матеріали', 'asset_current')
        cls.acc_23 = acc('23', 'Виробництво', 'asset_current')
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_411 = acc('411', 'Дооцінка основних засобів', 'equity')
        cls.acc_441 = acc('441', 'Прибуток нерозподілений', 'equity')
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_721 = acc('721', 'Дохід від інвестицій в асоційовані підприємства', 'income')
        cls.acc_732 = acc('732', 'Відсотки одержані', 'income')
        cls.acc_79 = acc('79', 'Фінансові результати', 'equity_unaffected')
        cls.acc_801 = acc('801', 'Витрати сировини й матеріалів', 'expense')
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
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': on_date,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount,
                        'partner_id': self.partner.id}),
                (0, 0, {'account_id': credit_account.id, 'credit': amount,
                        'partner_id': self.partner.id}),
            ],
        })
        move.action_post()
        return move

    def _report(self):
        report = self.env['l10n_ua.pnl.report'].create({
            'company_id': self.company.id,
            'date_from': date(2043, 1, 1),
            'date_to': date(2043, 12, 31),
        })
        report.action_compute()
        return report

    def _row(self, report, code):
        return report.line_ids.filtered(lambda l: l.code == code)

    def _amount(self, report, code):
        return self._row(report, code).current_amount

    def test_rows_follow_the_form(self):
        report = self._report()
        codes = [line.code for line in report.line_ids.sorted('sequence') if line.code]
        self.assertEqual(codes, [
            '2000', '2050', '2090', '2095', '2120', '2130', '2150', '2180', '2190', '2195',
            '2200', '2220', '2240', '2250', '2255', '2270', '2290', '2295', '2300', '2305',
            '2350', '2355',
            '2400', '2405', '2410', '2415', '2445', '2450', '2455', '2460', '2465',
            '2500', '2505', '2510', '2515', '2520', '2550',
            '2600', '2605', '2610', '2615', '2650'])

    def test_net_turnover_and_loss_rows(self):
        self._entry(self.acc_361, self.acc_702, 1000000)
        self._entry(self.acc_702, self.acc_361, 200000)      # повернення товару
        self._entry(self.acc_902, self.acc_281, 500000)
        self._entry(self.acc_92, self.acc_361, 400000)
        self._entry(self.acc_361, self.acc_721, 30000)
        self._entry(self.acc_361, self.acc_732, 20000)
        # The closing of the year through 79 changes nothing
        self._entry(self.acc_702, self.acc_79, 800000)
        self._entry(self.acc_79, self.acc_902, 500000)
        self._entry(self.acc_79, self.acc_92, 400000)

        report = self._report()
        amount = lambda code: self._amount(report, code)  # noqa: E731
        self.assertEqual(amount('2000'), 800000)
        self.assertEqual(amount('2050'), 500000)
        self.assertEqual((amount('2090'), amount('2095')), (300000, 0))
        self.assertEqual((amount('2190'), amount('2195')), (0, 100000))
        self.assertEqual(amount('2200'), 30000)
        self.assertEqual(amount('2220'), 20000)
        self.assertEqual((amount('2290'), amount('2295')), (0, 50000))
        self.assertEqual((amount('2350'), amount('2355')), (0, 50000))
        self.assertEqual(report.net_profit, -50000)

        values = report._xml_values()
        self.assertEqual(values['R2050G3'], 500)       # thousands; expense positive
        self.assertEqual(values['R2355G3'], 50)        # loss: positive
        self.assertNotIn('R2350G3', values)

        # A row entered by hand: profit of a discontinued operation
        self._row(report, '2305').current_amount = 120000
        self.assertEqual((amount('2350'), amount('2355')), (70000, 0))
        self.assertEqual(report.net_profit, 70000)

    def test_comprehensive_income(self):
        self._entry(self.acc_361, self.acc_702, 1000)
        self._entry(self.acc_104, self.acc_411, 300)
        self._entry(self.acc_411, self.acc_441, 100)   # реалізований дооцінений капітал
        report = self._report()
        self.assertEqual(self._amount(report, '2400'), 300)
        self.assertEqual(self._amount(report, '2450'), 300)
        self._row(report, '2455').current_amount = 54
        self.assertEqual(self._amount(report, '2460'), 246)
        self.assertEqual(self._amount(report, '2465'), 1000 + 246)

    def test_elements_of_operating_expenses(self):
        self._entry(self.acc_801, self.acc_201, 70)
        self._entry(self.acc_23, self.acc_801, 70)     # списання класу 8
        report = self._report()
        self.assertEqual(self._amount(report, '2500'), 70)
        self.assertEqual(self._amount(report, '2550'), 70)

    def test_only_manual_rows_are_edited(self):
        report = self._report()
        with self.assertRaises(UserError):
            self._row(report, '2000').current_amount = 1
        self._row(report, '2610').current_amount = 1.25
        self.assertEqual(report._xml_values()['R2610G3'], 1.25)

    def test_print(self):
        self._entry(self.acc_361, self.acc_702, 100000)
        self._entry(self.acc_92, self.acc_361, 300000)
        report = self._report()
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_pnl_document', report.ids)[0].decode()
        self.assertIn('II. СУКУПНИЙ ДОХІД', html)
        self.assertIn('(200)', html)  # loss in parentheses, thousands
        self.assertIn('тис. грн', html)
