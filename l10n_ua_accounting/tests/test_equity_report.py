"""Форма № 4 «Звіт про власний капітал» (#78).

Рахунки створюються тут, а дати — 2041 рік, тож тест не залежить від плану
рахунків і проводок бази.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.l10n_ua_accounting.models.l10n_ua_equity_report import (
    EQUITY_FIELDS, EQUITY_LINES, equity_row,
)

from .common import AccountingTestCase

D = date(2041, 6, 15)


@tagged('post_install', '-at_install', 'l10n_ua_accounting')
class TestEquityReport(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._account
        cls.acc_40 = acc('40', 'Зареєстрований капітал', 'equity')
        cls.acc_411 = acc('411', 'Дооцінка основних засобів', 'equity')
        cls.acc_43 = acc('43', 'Резервний капітал', 'equity')
        cls.acc_441 = acc('441', 'Прибуток нерозподілений', 'equity')
        cls.acc_443 = acc('443', 'Прибуток, використаний у звітному періоді', 'equity')
        cls.acc_451 = acc('451', 'Вилучені акції', 'equity')
        cls.acc_46 = acc('46', 'Неоплачений капітал', 'equity')
        cls.acc_301 = acc('301', 'Готівка', 'asset_cash')
        cls.acc_104 = acc('104', 'Машини та обладнання', 'asset_fixed')
        cls.acc_361 = acc('361', 'Розрахунки з покупцями', 'asset_receivable', True)
        cls.acc_671 = acc('671', 'Розрахунки за нарахованими дивідендами', 'liability_current')
        cls.acc_702 = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_79 = acc('79', 'Фінансові результати', 'equity_unaffected')
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
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'credit': 0.0,
                        'partner_id': self.partner.id}),
                (0, 0, {'account_id': credit_account.id, 'debit': 0.0, 'credit': amount,
                        'partner_id': self.partner.id}),
            ],
        })
        move.action_post()
        return move

    def _report(self):
        report = self.env['l10n_ua.equity.report'].create({
            'company_id': self.company.id,
            'date_from': date(2041, 1, 1),
            'date_to': date(2041, 12, 31),
        })
        report.action_compute()
        return report

    def _row(self, report, code):
        return report.line_ids.filtered(lambda l: l.code == code)

    def test_rows_follow_the_form(self):
        report = self._report()
        codes = [line.code for line in report.line_ids if line.code]
        # Rows of Додаток 1; the additional ones are left out without an amount
        self.assertEqual(codes, [
            '4000', '4005', '4010', '4090', '4095', '4100', '4110', '4200', '4205',
            '4210', '4240', '4245', '4260', '4265', '4270', '4275', '4290', '4295', '4300'])
        self.assertEqual(report.name, 'Звіт про власний капітал за 2041 рік')

    def test_movements_by_counterpart(self):
        # Founding: capital declared, partly paid in
        self._entry(self.acc_46, self.acc_40, 10000)
        self._entry(self.acc_301, self.acc_46, 6000)
        # Result of the year, then the closing through 79
        self._entry(self.acc_361, self.acc_702, 5000)
        self._entry(self.acc_92, self.acc_301, 1000)
        self._entry(self.acc_702, self.acc_79, 5000)
        self._entry(self.acc_79, self.acc_92, 1000)
        self._entry(self.acc_79, self.acc_441, 4000)
        # Distribution of the profit
        self._entry(self.acc_443, self.acc_671, 1000)
        self._entry(self.acc_443, self.acc_43, 500)
        # Revaluation of fixed assets, a buy-back of a share, an error corrected
        self._entry(self.acc_104, self.acc_411, 2000)
        self._entry(self.acc_451, self.acc_301, 300)
        self._entry(self.acc_441, self.acc_361, 100)

        report = self._report()
        row = lambda code: self._row(report, code)  # noqa: E731

        self.assertEqual((row('4240').registered, row('4240').unpaid, row('4240').total),
                         (10000, -10000, 0))
        self.assertEqual(row('4245').unpaid, 6000)
        # The closing of 79 does not change the result
        self.assertEqual(row('4100').retained, 4000)
        self.assertEqual(row('4200').retained, -1000)
        self.assertEqual((row('4210').retained, row('4210').reserve), (-500, 500))
        self.assertEqual(row('4111').revaluation, 2000)
        self.assertEqual(row('4110').revaluation, 2000)
        self.assertEqual(row('4260').withdrawn, -300)
        self.assertEqual(row('4290').retained, -100)
        # 4295 adds up the movements, not the parts of 4110
        self.assertEqual(row('4295').total, 6000 + 4000 - 1000 + 2000 - 300 - 100)
        self.assertEqual(row('4300').total, row('4000').total + row('4295').total)
        self.assertFalse(report.ledger_difference)

    def test_closing_balance_equals_the_ledger(self):
        self._entry(self.acc_46, self.acc_40, 10000)
        self._entry(self.acc_361, self.acc_702, 700)  # year not closed
        report = self._report()
        closing = report._column_balances([('date', '<=', date(2041, 12, 31))])
        for field in EQUITY_FIELDS:
            self.assertAlmostEqual(self._row(report, '4300')[field], closing[field], places=2)
        # Unclosed classes 7–9 are the result of the period, as row 1420
        self.assertEqual(self._row(report, '4100').retained, 700)

    def test_correction_is_taken_out_of_other_changes(self):
        self._entry(self.acc_441, self.acc_361, 100)
        report = self._report()
        closing_before = self._row(report, '4300').retained
        self._row(report, '4010').retained = -100
        self.assertEqual(self._row(report, '4290').retained, 0)
        self.assertEqual(self._row(report, '4095').retained,
                         self._row(report, '4000').retained - 100)
        self.assertEqual(self._row(report, '4300').retained, closing_before)
        self.assertFalse(report.ledger_difference)

    def test_only_corrections_are_edited_by_hand(self):
        report = self._report()
        with self.assertRaises(UserError):
            self._row(report, '4100').retained = 1
        report.action_confirm()
        with self.assertRaises(UserError):
            self._row(report, '4010').retained = 1

    def test_reserve_and_loss_cover(self):
        # Covering a loss from the reserve is not «відрахування»
        self.assertEqual(equity_row('reserve', '43', ['443'], 500), '4210')
        self.assertEqual(equity_row('reserve', '43', ['442'], -500), '4290')
        self.assertEqual(equity_row('retained', '442', ['43'], 500), '4290')
        self.assertEqual(equity_row('withdrawn', '451', ['301'], 300), '4265')
        self.assertEqual(equity_row('withdrawn', '451', ['40'], 300), '4270')

    def test_xml_values(self):
        self._entry(self.acc_46, self.acc_40, 10000.4)
        report = self._report()
        values = report._xml_values()
        self.assertEqual(values['R4240G3'], 10000)
        self.assertEqual(values['R4240G8'], -10000)
        self.assertNotIn('R4240G10', values)  # nothing in the total
        self.assertTrue(all(key[1:5] in {line[1] for line in EQUITY_LINES} for key in values))

    def test_print_and_xlsx(self):
        self._entry(self.acc_46, self.acc_40, 1000)
        report = self._report()
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_equity_document', report.ids)[0].decode()
        self.assertIn('Звіт про власний капітал', html)
        self.assertIn('4300', html)
        action = report.action_export_xlsx()
        self.assertIn('/web/content/', action['url'])
