"""Tests for the Cash Flow Statement (Звіт про рух грошових коштів, Ф.3).

Класифікація за прямим методом тримається на кореспондуючому рахунку, тому
кожен тест ставить одну проводку з відомим контр-рахунком і перевіряє, що
сума лягла саме в той рядок бланка, який вимагає НП(С)БО 1.
"""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import AccountingTestCase


# Період свідомо винесено в майбутнє: фікстури й демо-дані до нього не
# дотягуються, тож рядки-потоки містять рівно те, що ставить сам тест.
PERIOD_FROM = date(2035, 1, 1)
PERIOD_TO = date(2035, 12, 31)
IN_PERIOD = date(2035, 6, 15)


@tagged('post_install', '-at_install')
class TestCashflowReport(AccountingTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.acc_bank = cls._ensure_account('311', 'Рахунки в банку', 'asset_cash')
        cls.acc_cash_desk = cls._ensure_account('301', 'Каса в націнці', 'asset_cash')
        cls.acc_customers = cls._ensure_account('361', 'Розрахунки з покупцями', 'asset_receivable')
        cls.acc_suppliers = cls._ensure_account('631', 'Розрахунки з постачальниками', 'liability_payable')
        cls.acc_loans = cls._ensure_account('601', 'Короткострокові кредити банків', 'liability_current')
        cls.acc_capex = cls._ensure_account('152', 'Придбання основних засобів', 'asset_fixed')
        cls.acc_other_income = cls._ensure_account('719', 'Інші доходи операційної діяльності', 'income_other')

    @classmethod
    def _ensure_account(cls, code, name, account_type):
        account = cls.env['account.account'].search([
            ('code', '=', code),
            ('company_ids', 'in', cls.company.id),
        ], limit=1)
        if account:
            return account
        # chart_template_load: в Odoo 20 кожен створений рахунок типу
        # asset_cash тягне за собою власний банківський журнал, а два
        # журнали однієї компанії стикаються поштовим аліасом. Це рядки
        # плану рахунків, не нові рахунки в банку, тож користуємось тим
        # самим винятком, що й завантаження плану.
        return cls.env['account.account'].with_context(
            chart_template_load=True).create({
            'code': code,
            'name': name,
            'account_type': account_type,
            'company_ids': [(6, 0, [cls.company.id])],
            'reconcile': account_type in ('asset_receivable', 'liability_payable'),
        })

    def _post_move(self, debit_account, credit_account, amount, move_date=None):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.misc_journal.id,
            'date': move_date or IN_PERIOD,
            'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': credit_account.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def _computed_report(self, **overrides):
        vals = {
            'date_from': PERIOD_FROM,
            'date_to': PERIOD_TO,
            'company_id': self.company.id,
        }
        vals.update(overrides)
        report = self.env['l10n_ua.cashflow.report'].create(vals)
        report.action_compute()
        return report

    def _amount(self, report, code):
        line = report.line_ids.filtered(lambda l: l.code == code)
        self.assertTrue(line, f'Рядок {code} відсутній у звіті')
        return line.current_amount

    # ── Класифікація потоків ────────────────────────────────

    def test_cashflow_report_xlsx_export(self):
        """XLSX-експорт Ф.3 створює вкладення з файлом (#606)."""
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        report = self._computed_report()
        self.assertXlsxExport(report.action_export_xlsx())

    def test_customer_receipt_is_operating_inflow(self):
        """Дт 311 / Кт 361 — надходження від реалізації, рядок 3000."""
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3000'), 1000.0)
        self.assertEqual(self._amount(report, '3195'), 1000.0)

    def test_supplier_payment_is_operating_outflow(self):
        """Дт 631 / Кт 311 — витрачання на оплату товарів, рядок 3100."""
        self._post_move(self.acc_suppliers, self.acc_bank, 600.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3100'), 600.0)
        self.assertEqual(self._amount(report, '3195'), -600.0)

    def test_loan_receipt_is_financing_inflow(self):
        """Дт 311 / Кт 601 — отримання позики, рядок 3305, не 3000."""
        self._post_move(self.acc_bank, self.acc_loans, 5000.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3305'), 5000.0)
        self.assertEqual(self._amount(report, '3000'), 0.0)
        self.assertEqual(self._amount(report, '3395'), 5000.0)

    def test_capex_payment_is_investing_outflow(self):
        """Дт 152 / Кт 311 — придбання необоротних активів, рядок 3260."""
        self._post_move(self.acc_capex, self.acc_bank, 2500.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3260'), 2500.0)
        self.assertEqual(self._amount(report, '3295'), -2500.0)

    def test_unclassified_counterpart_falls_into_other_operating(self):
        """Контр-рахунок без власного рядка бланка йде в «інші», рядок 3095."""
        self._post_move(self.acc_bank, self.acc_other_income, 300.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3095'), 300.0)

    def test_transfer_between_cash_accounts_is_not_a_flow(self):
        """Переказ з каси на рахунок у банку — не рух коштів підприємства."""
        self._post_move(self.acc_bank, self.acc_cash_desk, 700.0)

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3400'), 0.0)
        self.assertEqual(self._amount(report, '3095'), 0.0)
        self.assertEqual(self._amount(report, '3190'), 0.0)
        self.assertEqual(self._amount(report, '3405'), self._amount(report, '3415'))

    def test_sections_add_up_to_net_cash_flow(self):
        """Рядок 3400 — сума трьох розділів, а не окремий підрахунок."""
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        self._post_move(self.acc_suppliers, self.acc_bank, 600.0)
        self._post_move(self.acc_bank, self.acc_loans, 5000.0)
        self._post_move(self.acc_capex, self.acc_bank, 2500.0)

        report = self._computed_report()

        self.assertEqual(
            self._amount(report, '3400'),
            self._amount(report, '3195')
            + self._amount(report, '3295')
            + self._amount(report, '3395'),
        )
        self.assertEqual(self._amount(report, '3400'), 1000.0 - 600.0 + 5000.0 - 2500.0)

    def test_closing_balance_reconciles_with_opening_and_flows(self):
        """3415 = 3405 + 3400 + 3410 — тотожність бланка має триматися."""
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        self._post_move(self.acc_suppliers, self.acc_bank, 600.0)

        report = self._computed_report()

        self.assertAlmostEqual(
            self._amount(report, '3415'),
            self._amount(report, '3405')
            + self._amount(report, '3400')
            + self._amount(report, '3410'),
            places=2,
        )

    def test_opening_balance_excludes_the_reporting_period(self):
        """Залишок на початок року не має вбирати рухи звітного періоду."""
        baseline = self._computed_report()
        opening_before = self._amount(baseline, '3405')

        self._post_move(self.acc_bank, self.acc_customers, 400.0,
                        move_date=date(2034, 12, 31))
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        report = self._computed_report()

        # 400 грн минулого року підняли вхідний залишок; 1000 грн звітного
        # періоду — ні, вони пішли в потік.
        self.assertEqual(self._amount(report, '3405'), opening_before + 400.0)
        self.assertEqual(self._amount(report, '3000'), 1000.0)

    def test_moves_outside_the_period_are_ignored(self):
        self._post_move(self.acc_bank, self.acc_customers, 900.0,
                        move_date=date(2036, 3, 1))

        report = self._computed_report()

        self.assertEqual(self._amount(report, '3000'), 0.0)

    def test_comparison_period_is_filled_separately(self):
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        self._post_move(self.acc_bank, self.acc_customers, 250.0,
                        move_date=date(2034, 6, 15))

        report = self._computed_report(
            comparison_date_from=date(2034, 1, 1),
            comparison_date_to=date(2034, 12, 31),
        )
        line = report.line_ids.filtered(lambda l: l.code == '3000')

        self.assertEqual(line.current_amount, 1000.0)
        self.assertEqual(line.previous_amount, 250.0)

    # ── Життєвий цикл ───────────────────────────────────────

    def test_state_workflow(self):
        report = self._computed_report()

        report.action_confirm()
        self.assertEqual(report.state, 'confirmed')
        report.action_draft()
        self.assertEqual(report.state, 'draft')

    def test_confirmed_report_cannot_be_recalculated(self):
        report = self._computed_report()
        report.action_confirm()

        with self.assertRaises(UserError):
            report.action_compute()

    def test_empty_report_cannot_be_confirmed(self):
        report = self.env['l10n_ua.cashflow.report'].create({
            'date_from': PERIOD_FROM,
            'date_to': PERIOD_TO,
            'company_id': self.company.id,
        })

        with self.assertRaises(UserError):
            report.action_confirm()

    def test_reversed_period_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env['l10n_ua.cashflow.report'].create({
                'date_from': PERIOD_TO,
                'date_to': PERIOD_FROM,
                'company_id': self.company.id,
            })

    def test_recompute_replaces_lines_instead_of_appending(self):
        report = self._computed_report()
        first_count = len(report.line_ids)

        report.action_compute()

        self.assertEqual(len(report.line_ids), first_count)

    # ── Друк і деталізація ──────────────────────────────────

    def test_qweb_report_renders(self):
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        self._post_move(self.acc_capex, self.acc_bank, 2500.0)
        report = self._computed_report()

        html, _report_type = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_cashflow_document', report.ids)
        rendered = html.decode()

        self.assertIn('ЗВІТ ПРО РУХ ГРОШОВИХ КОШТІВ', rendered)
        self.assertIn('I. Рух коштів у результаті операційної діяльності', rendered)
        self.assertIn('III. Рух коштів у результаті фінансової діяльності', rendered)

    def test_drill_down_returns_the_lines_behind_a_row(self):
        self._post_move(self.acc_bank, self.acc_customers, 1000.0)
        report = self._computed_report()
        line = report.line_ids.filtered(lambda l: l.code == '3000')

        action = line.action_view_move_lines()
        matched = self.env['account.move.line'].search(action['domain'])

        self.assertEqual(matched.mapped('account_id'), self.acc_customers)

    def test_drill_down_works_for_the_other_rows(self):
        """3095 збирається з проводок, тож має деталізацію нарівні з рештою."""
        self._post_move(self.acc_bank, self.acc_other_income, 300.0)
        report = self._computed_report()
        line = report.line_ids.filtered(lambda l: l.code == '3095')

        action = line.action_view_move_lines()
        matched = self.env['account.move.line'].search(action['domain'])

        self.assertEqual(matched.mapped('account_id'), self.acc_other_income)

    def test_drill_down_is_disabled_for_computed_rows(self):
        report = self._computed_report()
        subtotal = report.line_ids.filtered(lambda l: l.code == '3195')

        self.assertFalse(subtotal.action_view_move_lines())


@tagged('post_install', '-at_install')
class TestCashflowForm(AccountingTestCase):
    """Коди рядків за Додатком 1 до НП(С)БО 1 і непрямий метод (Ф3-н) — #78."""

    _ensure_account = TestCashflowReport.__dict__['_ensure_account']
    _post_move = TestCashflowReport._post_move
    _computed_report = TestCashflowReport._computed_report
    _amount = TestCashflowReport._amount

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        acc = cls._ensure_account
        cls.acc_bank = acc('311', 'Рахунки в банку', 'asset_cash')
        cls.acc_customers = acc('361', 'Розрахунки з покупцями', 'asset_receivable')
        cls.acc_suppliers = acc('631', 'Розрахунки з постачальниками', 'liability_payable')
        cls.acc_loans = acc('601', 'Короткострокові кредити банків', 'liability_current')
        cls.acc_goods = acc('281', 'Товари на складі', 'asset_current')
        cls.acc_revenue = acc('702', 'Дохід від реалізації товарів', 'income')
        cls.acc_cogs = acc('902', 'Собівартість реалізованих товарів', 'expense_direct_cost')
        cls.acc_admin = acc('92', 'Адміністративні витрати', 'expense')
        cls.acc_depr = acc('131', 'Знос основних засобів', 'asset_fixed')
        cls.acc_profit_tax = acc('6413', 'Розрахунки за податком на прибуток', 'liability_current')
        cls.acc_tax_expense = acc('981', 'Податок на прибуток', 'expense')
        cls.acc_securities = acc('351', 'Еквіваленти грошових коштів', 'asset_current')
        cls.acc_dividends = acc('671', 'Розрахунки за нарахованими дивідендами', 'liability_current')

    def test_official_codes_of_sections_ii_and_iii(self):
        report = self._computed_report()
        codes = [line.code for line in report.line_ids.sorted('sequence')]
        start = codes.index('3200')
        self.assertEqual(codes[start:], [
            '3200', '3205', '3215', '3220', '3225', '3250', '3255', '3260', '3270', '3290', '3295',
            '3300', '3305', '3340', '3345', '3350', '3355', '3390', '3395',
            '3400', '3405', '3410', '3415'])

    def test_current_investments_are_not_cash(self):
        """35 is row 1160 of the balance, not 1165: buying it is an investment."""
        self._post_move(self.acc_securities, self.acc_bank, 1000000.0)
        report = self._computed_report()
        self.assertEqual(self._amount(report, '3255'), 1000000.0)
        self.assertEqual(self._amount(report, '3410'), 0.0)

    def test_tax_parts_and_dividends(self):
        self._post_move(self.acc_profit_tax, self.acc_bank, 300000.0)
        self._post_move(self.acc_dividends, self.acc_bank, 200000.0)
        report = self._computed_report()
        self.assertEqual(self._amount(report, '3115'), 300000.0)
        self.assertEqual(self._amount(report, '3116'), 300000.0)
        self.assertNotIn('3117', report.line_ids.mapped('code'))
        self.assertEqual(self._amount(report, '3355'), 200000.0)
        values = report._xml_values()
        self.assertEqual(values['R3116G3'], 300)
        self.assertEqual(values['R3355G3'], 200)

    def _scenario(self):
        self._post_move(self.acc_customers, self.acc_revenue, 1000000.0)
        self._post_move(self.acc_cogs, self.acc_goods, 600000.0)
        self._post_move(self.acc_bank, self.acc_customers, 700000.0)
        self._post_move(self.acc_goods, self.acc_suppliers, 500000.0)
        self._post_move(self.acc_suppliers, self.acc_bank, 400000.0)
        self._post_move(self.acc_admin, self.acc_depr, 50000.0)
        self._post_move(self.acc_tax_expense, self.acc_profit_tax, 30000.0)
        self._post_move(self.acc_profit_tax, self.acc_bank, 30000.0)
        self._post_move(self.acc_bank, self.acc_loans, 1000000.0)

    def test_indirect_method_agrees_with_direct(self):
        self._scenario()
        direct = self._computed_report()
        indirect = self._computed_report(method='indirect')
        amount = lambda code: self._amount(indirect, code)  # noqa: E731

        self.assertEqual(self._amount(direct, '3195'), 270000.0)
        self.assertEqual(amount('3195'), 270000.0)
        self.assertEqual(amount('3500'), 350000.0)      # 1000 − 600 − 50, before tax
        self.assertEqual(amount('3505'), 50000.0)
        self.assertEqual(amount('3551'), 100000.0)      # goods: −600 + 500
        self.assertEqual(amount('3553'), -300000.0)     # receivables grew
        self.assertEqual(amount('3561'), 100000.0)      # payables grew
        self.assertEqual(amount('3550'), -200000.0)
        self.assertEqual(amount('3580'), -30000.0)
        self.assertEqual(amount('3570'), 300000.0)
        self.assertEqual(amount('3520'), 0.0)        # nothing left unexplained
        self.assertEqual(amount('3400'), self._amount(direct, '3400'))
        self.assertEqual(amount('3305'), 1000000.0)
        self.assertNotIn('3000', indirect.line_ids.mapped('code'))

        values = indirect._xml_values()
        self.assertEqual(values['R3500G3'], 350)
        self.assertEqual(values['R3553G4'], 300)     # a decrease of cash: видаток
        self.assertEqual(values['R3580G4'], 30)
        self.assertEqual(values['R3305G3'], 1000)

    def test_indirect_report_renders(self):
        self._scenario()
        report = self._computed_report(method='indirect')
        html = self.env['ir.actions.report']._render_qweb_html(
            'l10n_ua_accounting.report_cashflow_document', report.ids)[0].decode()
        self.assertIn('за непрямим методом', html)
        self.assertIn('надходження', html)
