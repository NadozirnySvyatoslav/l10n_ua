"""Тести комерційного бюджетування: періоди, факт БДР/БДДС, сценарії, Excel, контроль."""

import base64
import io
from datetime import date

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


# Період у майбутньому: демо-дані й фікстури бази до нього не дотягуються.
YEAR = 2035


@tagged('post_install', '-at_install')
class TestBudgetCommercial(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Account = cls.env['account.account']

        def account(code, name, account_type, reconcile=False):
            return Account.create({
                'code': code, 'name': name, 'account_type': account_type,
                'company_ids': [Command.set(cls.company.ids)], 'reconcile': reconcile,
            })

        cls.acc_expense = account('929901', 'Адмінвитрати (тест)', 'expense')
        cls.acc_income = account('709901', 'Дохід (тест)', 'income')
        cls.acc_payable = account('639901', 'Постачальники (тест)', 'liability_payable', True)
        cls.acc_receivable = account('369901', 'Покупці (тест)', 'asset_receivable', True)
        cls.acc_bank = account('319901', 'Банк (тест)', 'asset_cash')
        cls.journal = cls.env['account.journal'].create({
            'name': 'Бюджет (тест)', 'code': 'BDGT', 'type': 'general',
            'company_id': cls.company.id,
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Постачальник бюджету'})

        Item = cls.env['l10n_ua.budget.item']
        cls.item_admin = Item.create({
            'name': 'Адмінвитрати', 'code': 'TB01', 'budget_type': 'pnl',
            'item_type': 'expense', 'account_ids': [Command.set(cls.acc_expense.ids)],
        })
        cls.item_sales = Item.create({
            'name': 'Реалізація', 'code': 'TB02', 'budget_type': 'pnl',
            'item_type': 'income', 'account_ids': [Command.set(cls.acc_income.ids)],
        })
        cls.item_pay_suppliers = Item.create({
            'name': 'Оплата постачальникам', 'code': 'TC01', 'budget_type': 'cash',
            'item_type': 'expense', 'account_ids': [Command.set(cls.acc_payable.ids)],
        })
        cls.item_receipts = Item.create({
            'name': 'Надходження від покупців', 'code': 'TC02', 'budget_type': 'cash',
            'item_type': 'income', 'account_codes': '369901',
        })

        analytic_plan = cls.env['account.analytic.plan'].create({'name': 'ЦФВ (тест)'})
        cls.center = cls.env['account.analytic.account'].create({
            'name': 'Відділ продажів', 'code': 'SALES', 'plan_id': analytic_plan.id,
            'company_id': cls.company.id,
        })

    # ------------------------------------------------------------------

    def _plan(self, budget_type='pnl', period_type='month', **vals):
        return self.env['l10n_ua.budget.plan'].create(dict({
            'name': f'Бюджет {YEAR}',
            'budget_type': budget_type,
            'period_type': period_type,
            'date_from': date(YEAR, 1, 1),
            'date_to': date(YEAR, 12, 31),
            'company_id': self.company.id,
        }, **vals))

    def _line(self, plan, item, month, amount, **vals):
        return self.env['l10n_ua.budget.line'].create(dict({
            'plan_id': plan.id,
            'item_id': item.id,
            'date_from': date(YEAR, month, 1),
            'date_to': plan._get_buckets()[month - 1][1],
            'planned_amount': amount,
        }, **vals))

    def _entry(self, debit_account, credit_account, amount, month=2, debit_analytic=None):
        debit_line = {'account_id': debit_account.id, 'debit': amount, 'credit': 0.0}
        if debit_analytic:
            debit_line['analytic_distribution'] = debit_analytic
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date(YEAR, month, 10),
            'line_ids': [
                Command.create(debit_line),
                Command.create({'account_id': credit_account.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    # ------------------------------------------------------------------

    def test_buckets_and_generate_lines(self):
        plan = self._plan(period_type='quarter')
        self.assertEqual(len(plan._get_buckets()), 4)
        self.assertEqual(plan._get_buckets()[0], (date(YEAR, 1, 1), date(YEAR, 3, 31)))
        self.assertEqual(plan._bucket_label(date(YEAR, 4, 1)), f'{YEAR}-Q2')
        plan.action_generate_lines()
        admin_lines = plan.line_ids.filtered(lambda l: l.item_id == self.item_admin)
        self.assertEqual(len(admin_lines), 4)
        self.assertFalse(plan.line_ids.item_id.filtered(lambda i: i.budget_type != 'pnl'))
        # Повторна генерація не дублює рядки.
        count = len(plan.line_ids)
        plan.action_generate_lines()
        self.assertEqual(len(plan.line_ids), count)

    def test_period_constraints(self):
        with self.assertRaises(ValidationError):
            self._plan(date_from=date(YEAR, 1, 15))
        with self.assertRaises(ValidationError):
            self._plan(period_type='quarter', date_from=date(YEAR, 2, 1))
        plan = self._plan()
        with self.assertRaises(ValidationError):
            self.env['l10n_ua.budget.line'].create({
                'plan_id': plan.id, 'item_id': self.item_admin.id,
                'date_from': date(YEAR + 1, 1, 1), 'date_to': date(YEAR + 1, 1, 31),
            })
        with self.assertRaises(ValidationError):
            self._line(plan, self.item_pay_suppliers, 1, 100)

    def test_pnl_actuals(self):
        plan = self._plan()
        admin_feb = self._line(plan, self.item_admin, 2, 800)
        admin_mar = self._line(plan, self.item_admin, 3, 500)
        sales_feb = self._line(plan, self.item_sales, 2, 5000)
        self._entry(self.acc_expense, self.acc_payable, 1000)
        self._entry(self.acc_receivable, self.acc_income, 4000)
        plan.action_refresh_actuals()
        self.assertEqual(admin_feb.actual_amount, 1000)
        self.assertEqual(admin_feb.variance_amount, 200)
        self.assertTrue(admin_feb.is_over_budget)
        self.assertEqual(admin_mar.actual_amount, 0)
        self.assertEqual(sales_feb.actual_amount, 4000)
        self.assertAlmostEqual(sales_feb.execution_pct, 80.0)
        self.assertFalse(sales_feb.is_over_budget)
        # Результат плану: доходи − витрати.
        self.assertEqual(plan.amount_planned, 5000 - 1300)
        self.assertEqual(plan.amount_actual, 4000 - 1000)
        self.assertTrue(plan.actuals_date)

    def test_analytic_weighting(self):
        plan = self._plan(analytic_account_id=self.center.id, level='center')
        line = self._line(plan, self.item_admin, 2, 1000)
        self.assertEqual(line.analytic_account_id, self.center)
        self._entry(self.acc_expense, self.acc_payable, 600,
                    debit_analytic={str(self.center.id): 50.0})
        self._entry(self.acc_expense, self.acc_payable, 999)  # без аналітики
        plan.action_refresh_actuals()
        self.assertEqual(line.actual_amount, 300)

    def test_cash_actuals(self):
        plan = self._plan(budget_type='cash')
        out_line = self._line(plan, self.item_pay_suppliers, 2, 1000)
        in_line = self._line(plan, self.item_receipts, 2, 1000)
        self._entry(self.acc_expense, self.acc_payable, 700)   # нарахування, не гроші
        self._entry(self.acc_payable, self.acc_bank, 300)      # оплата постачальнику
        self._entry(self.acc_bank, self.acc_receivable, 450)   # оплата від покупця
        self._entry(self.acc_receivable, self.acc_income, 900)  # реалізація, не гроші
        plan.action_refresh_actuals()
        self.assertEqual(out_line.actual_amount, 300)
        self.assertEqual(in_line.actual_amount, 450)
        action = out_line.action_open_journal_items()
        self.assertEqual(self.env['account.move.line'].search(action['domain']).mapped('debit'), [300.0])

    def test_workflow_locks_plan(self):
        plan = self._plan()
        line = self._line(plan, self.item_admin, 1, 100)
        plan.action_approve()
        self.assertEqual(plan.state, 'approved')
        self.env['l10n_ua.budget.plan']._cron_refresh_actuals()
        with self.assertRaises(UserError):
            line.planned_amount = 200
        with self.assertRaises(UserError):
            self._line(plan, self.item_admin, 2, 100)
        with self.assertRaises(UserError):
            plan.unlink()
        plan.action_close()
        self.assertEqual(plan.state, 'closed')
        plan.action_reset_draft()
        line.planned_amount = 200
        self.assertEqual(line.planned_amount, 200)
        with self.assertRaises(UserError):
            self._plan(name='Порожній').action_approve()

    def test_copy_to_scenario_and_period(self):
        parent = self._plan()
        self._line(parent, self.item_admin, 2, 1000)
        child = self._plan(name='ЦФВ', parent_id=parent.id, level='center',
                           analytic_account_id=self.center.id)
        self._line(child, self.item_admin, 2, 400)
        wizard = self.env['l10n_ua.budget.copy.wizard'].with_context(active_id=parent.id).create({
            'name': f'Бюджет {YEAR + 1} оптимістичний',
            'scenario': 'optimistic',
            'shift_months': 12,
            'coefficient': 110,
        })
        action = wizard.action_copy()
        new_plan = self.env['l10n_ua.budget.plan'].browse(action['res_id'])
        self.assertEqual(new_plan.scenario, 'optimistic')
        self.assertEqual(new_plan.state, 'draft')
        self.assertEqual(new_plan.source_plan_id, parent)
        self.assertEqual((new_plan.date_from, new_plan.date_to), (date(YEAR + 1, 1, 1), date(YEAR + 1, 12, 31)))
        self.assertEqual(new_plan.line_ids.planned_amount, 1100)
        self.assertEqual(new_plan.line_ids.date_to, date(YEAR + 1, 2, 29))  # 2036 — високосний
        self.assertEqual(len(new_plan.child_ids), 1)
        self.assertEqual(new_plan.child_ids.line_ids.planned_amount, 440)
        self.assertEqual(new_plan.child_ids.analytic_account_id, self.center)
        # Аналіз з батьківського плану охоплює дочірні.
        domain = new_plan.action_open_lines()['domain']
        self.assertEqual(len(self.env['l10n_ua.budget.line'].search(domain)), 2)

    def test_xlsx_round_trip(self):
        import openpyxl
        plan = self._plan(period_type='quarter')
        self.env['l10n_ua.budget.line'].create({
            'plan_id': plan.id, 'item_id': self.item_admin.id,
            'date_from': date(YEAR, 1, 1), 'date_to': date(YEAR, 3, 31), 'planned_amount': 900,
        })
        wizard = self.env['l10n_ua.budget.xlsx.wizard'].create({'plan_id': plan.id, 'mode': 'export'})
        wizard.action_export()
        workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(wizard.file_data)))
        sheet = workbook.worksheets[0]
        headers = [c.value for c in sheet[1]]
        self.assertEqual(headers[3:7], [f'{YEAR}-Q1', f'{YEAR}-Q2', f'{YEAR}-Q3', f'{YEAR}-Q4'])
        self.assertEqual(sheet.cell(2, 1).value, 'TB01')
        self.assertEqual(sheet.cell(2, 4).value, 900)

        # Правка в Excel: Q1 змінено, Q2 заповнено, додано статтю доходу з ЦФВ.
        sheet.cell(2, 4).value = 1200
        sheet.cell(2, 5).value = 300
        sheet.append(['TB02', 'Реалізація', 'SALES', 10000, None, None, None])
        buf = io.BytesIO()
        workbook.save(buf)

        importer = self.env['l10n_ua.budget.xlsx.wizard'].create({
            'plan_id': plan.id, 'mode': 'import', 'file_data': base64.b64encode(buf.getvalue()),
        })
        importer.action_import()
        admin = plan.line_ids.filtered(lambda l: l.item_id == self.item_admin).sorted('date_from')
        self.assertEqual(admin.mapped('planned_amount'), [1200, 300])
        sales = plan.line_ids.filtered(lambda l: l.item_id == self.item_sales)
        self.assertEqual(sales.planned_amount, 10000)
        self.assertEqual(sales.analytic_account_id, self.center)
        self.assertIn('2', importer.import_result)

        bad = io.BytesIO()
        workbook.worksheets[0].append(['NOPE', 'Немає такої', None, 1])
        workbook.save(bad)
        with self.assertRaises(UserError):
            self.env['l10n_ua.budget.xlsx.wizard'].create({
                'plan_id': plan.id, 'mode': 'import', 'file_data': base64.b64encode(bad.getvalue()),
            }).action_import()

    def test_account_code_prefixes(self):
        item = self.env['l10n_ua.budget.item'].create({
            'name': 'Префікси', 'budget_type': 'pnl', 'item_type': 'expense',
            'account_codes': '9299, 7099',
        })
        accounts = item._get_accounts(self.company)
        self.assertIn(self.acc_expense, accounts)
        self.assertIn(self.acc_income, accounts)
        self.assertNotIn(self.acc_payable, accounts)
        # Батьківська стаття бере рахунки підстатей.
        parent = self.env['l10n_ua.budget.item'].create({
            'name': 'Усі витрати', 'budget_type': 'pnl', 'item_type': 'expense',
        })
        self.item_admin.parent_id = parent
        self.assertIn(self.acc_expense, parent._get_accounts(self.company))

    # ------------------------------------------------------------------
    # Контроль бюджету
    # ------------------------------------------------------------------

    def _vendor_bill(self, amount):
        return self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date(YEAR, 2, 15),
            'date': date(YEAR, 2, 15),
            'invoice_line_ids': [Command.create({
                'name': 'Послуги',
                'account_id': self.acc_expense.id,
                'quantity': 1,
                'price_unit': amount,
                'tax_ids': [Command.clear()],
            })],
        })

    def _approved_admin_budget(self, amount):
        plan = self._plan()
        line = self._line(plan, self.item_admin, 2, amount)
        plan.action_approve()
        return line

    def test_budget_control_disabled_by_default(self):
        self.assertEqual(self.company.l10n_ua_budget_control, 'none')
        line = self._approved_admin_budget(100)
        bill = self._vendor_bill(500)
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(line.actual_amount, 0)  # без контролю факт не перераховується одразу

    def test_budget_control_block(self):
        self.company.l10n_ua_budget_control = 'block'
        self._approved_admin_budget(1000)
        self._vendor_bill(600).action_post()
        with self.assertRaises(UserError):
            self._vendor_bill(600).action_post()

    def test_budget_control_warning(self):
        self.company.l10n_ua_budget_control = 'warning'
        line = self._approved_admin_budget(100)
        bill = self._vendor_bill(500)
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(line.actual_amount, 500)
        self.assertTrue(line.is_over_budget)
        self.assertTrue(any('TB01' in (m.body or '') for m in bill.message_ids))

    def test_multicompany_rule(self):
        other = self.env['res.company'].create({'name': 'Інша компанія (бюджет)'})
        plan = self._plan(company_id=other.id)
        user = self.env['res.users'].create({
            'name': 'Бухгалтер', 'login': 'budget_accountant',
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'group_ids': [Command.set([self.env.ref('account.group_account_user').id])],
        })
        Plan = self.env['l10n_ua.budget.plan'].with_user(user)
        self.assertNotIn(plan, Plan.search([]))
