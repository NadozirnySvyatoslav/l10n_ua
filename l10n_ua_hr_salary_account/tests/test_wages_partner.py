"""Рядки 661/685 у проводках по ЗП мають партнера-працівника (#578, #588).

Без партнера ОСВ по 661 не розгортається по працівниках, а виплату ЗП
банком не звірити з нарахуванням конкретної людини.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.l10n_ua_hr_salary.tests.common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestWagesPartner(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def acc(code, name, atype):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': atype,
                'company_ids': [(4, cls.company.id)]})
        cls.acc_expense = acc('9200P', 'Адмінвитрати ЗП', 'expense')
        cls.acc_661 = acc('6610P', 'ЗП до виплати', 'liability_payable')
        cls.acc_651 = acc('6510P', 'ЄСВ', 'liability_current')
        cls.acc_6411 = acc('6411P', 'ПДФО', 'liability_current')
        cls.acc_6415 = acc('6415P', 'Військовий збір', 'liability_current')
        cls.acc_685 = acc('6850P', 'Інші кредитори', 'liability_current')
        cls.acc_311 = acc('3110P', 'Поточний рахунок', 'asset_cash')

        cls.journal = cls.env['account.journal'].create({
            'name': 'Зарплата', 'type': 'general', 'code': 'SALP',
            'company_id': cls.company.id})

        cfg_vals = {
            'salary_journal_id': cls.journal.id,
            'wages_payable_account_id': cls.acc_661.id,
            'pdfo_payable_account_id': cls.acc_6411.id,
            'military_tax_payable_account_id': cls.acc_6415.id,
            'esv_payable_account_id': cls.acc_651.id,
            'other_payable_account_id': cls.acc_685.id,
            'default_expense_account_id': cls.acc_expense.id,
            'auto_post': True,
        }
        cls.config = cls.env['hr.salary.account.config'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if cls.config:
            cls.config.write(cfg_vals)
        else:
            cls.config = cls.env['hr.salary.account.config'].create(
                dict(cfg_vals, company_id=cls.company.id))

        cls.type_alimony = cls.env.ref(
            'l10n_ua_hr_salary.deduction_type_alimony')

        # Ще два працівники з різними окладами — разом три.
        cls.employees = [(cls.employee, cls.version)]
        for name, rnokpp, wage in (
                ('Коваленко Ірина Петрівна', '2812345684', 18000),
                ('Шевчук Андрій Іванович', '2812345690', 32000)):
            emp = cls.env['hr.employee'].create({
                'name': name,
                'rnokpp': rnokpp,
                'company_id': cls.company.id,
                'department_id': cls.department.id,
                'job_id': cls.job.id,
            })
            version = cls.env['hr.version'].create({
                'employee_id': emp.id,
                'contract_date_start': date(2024, 1, 15),
                'date_version': date(2024, 1, 15),
                'wage': wage,
                'contract_type_ua': 'permanent',
                'employment_type_ua': 'primary',
                'company_id': cls.company.id,
            })
            emp.write({'current_version_id': version.id})
            cls.employees.append((emp, version))

    def _slip(self, employee, version, alimony=0.0):
        slip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'version_id': version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        slip.write({
            'scheduled_hours': 160.0, 'scheduled_days': 20,
            'worked_days': 20, 'worked_hours': 160.0,
        })
        slip.action_compute_sheet()
        if alimony:
            slip.write({'deduction_ids': [(0, 0, {
                'deduction_type_id': self.type_alimony.id,
                'amount': alimony})]})
        self.assertTrue(slip.gross_salary, 'Має бути ненульове нарахування')
        return slip

    def _closed_run(self):
        run = self.env['hr.payslip.run'].create({
            'name': 'Червень 2025',
            'date_start': date(2025, 6, 1),
            'date_end': date(2025, 6, 30),
            'company_id': self.company.id,
        })
        slips = self.env['hr.payslip']
        for i, (emp, version) in enumerate(self.employees):
            slips |= self._slip(emp, version, alimony=1000.0 if i == 0 else 0)
        slips.write({'payslip_run_id': run.id, 'state': 'done'})
        run._create_consolidated_move(self.config)
        self.assertTrue(run.move_id)
        return run, slips

    def _balance_661(self, partner):
        lines = self.env['account.move.line'].search([
            ('account_id', '=', self.acc_661.id),
            ('partner_id', '=', partner.id),
            ('parent_state', '=', 'posted'),
        ])
        return round(sum(lines.mapped('balance')), 2)

    # --- per payslip ---------------------------------------------------

    def test_per_payslip_661_685_have_employee_partner(self):
        emp, version = self.employees[0]
        slip = self._slip(emp, version, alimony=1000.0)
        lines = slip._prepare_move_lines(self.config)
        partner = emp.work_contact_id
        self.assertTrue(partner)
        wages = [l for l in lines if l['account_id'] in (
            self.acc_661.id, self.acc_685.id)]
        self.assertTrue(wages)
        for line in wages:
            self.assertEqual(line.get('partner_id'), partner.id, line['name'])
        # Рахунки витрат і податків — як і раніше, без партнера.
        others = [l for l in lines if l['account_id'] not in (
            self.acc_661.id, self.acc_685.id)]
        self.assertFalse([l for l in others if l.get('partner_id')])

    def test_employee_without_work_contact_clear_error(self):
        emp, version = self.employees[1]
        slip = self._slip(emp, version)
        emp.work_contact_id = False
        with self.assertRaisesRegex(UserError, 'Коваленко Ірина Петрівна'):
            slip._prepare_move_lines(self.config)

    # --- per batch -----------------------------------------------------

    def test_per_batch_661_line_per_employee(self):
        run, slips = self._closed_run()
        lines = run.move_id.line_ids
        lines_661 = lines.filtered(lambda l: l.account_id == self.acc_661)
        self.assertFalse(lines_661.filtered(lambda l: not l.partner_id),
                         'Кожен рядок 661 має партнера-працівника')
        partners = {e.work_contact_id for e, _v in self.employees}
        self.assertEqual(set(lines_661.mapped('partner_id')), partners)
        # Нарахування: один кредитовий рядок 661 на працівника.
        accrual = lines_661.filtered(lambda l: l.credit)
        self.assertEqual(len(accrual), 3)
        # 685 (аліменти) — лише у першого працівника, з його партнером.
        lines_685 = lines.filtered(lambda l: l.account_id == self.acc_685)
        self.assertEqual(lines_685.partner_id,
                         self.employees[0][0].work_contact_id)
        self.assertAlmostEqual(sum(lines_685.mapped('credit')), 1000.0)

    def test_per_batch_totals_unchanged(self):
        """Сумарні обороти по рахунках = сумам листків (як до #578)."""
        run, slips = self._closed_run()
        lines = run.move_id.line_ids

        def total(account, side):
            return round(sum(lines.filtered(
                lambda l: l.account_id == account).mapped(side)), 2)

        gross = round(sum(slips.mapped('gross_salary')), 2)
        pdfo = round(sum(slips.mapped('pdfo_amount')), 2)
        military = round(sum(slips.mapped('military_tax_amount')), 2)
        self.assertAlmostEqual(total(self.acc_661, 'credit'), gross)
        self.assertAlmostEqual(
            total(self.acc_661, 'debit'), pdfo + military + 1000.0)
        self.assertAlmostEqual(total(self.acc_6411, 'credit'), pdfo)
        self.assertAlmostEqual(total(self.acc_6415, 'credit'), military)
        self.assertAlmostEqual(total(self.acc_685, 'credit'), 1000.0)
        # Податкові рахунки — як і раніше, одним рядком.
        self.assertEqual(len(lines.filtered(
            lambda l: l.account_id == self.acc_6411)), 1)

    def test_per_batch_balance_per_employee_and_payment(self):
        """Сальдо 661 по працівнику = його «до виплати»; після виплати — 0."""
        run, slips = self._closed_run()
        for slip in slips:
            partner = slip.employee_id.work_contact_id
            self.assertAlmostEqual(
                -self._balance_661(partner), slip.net_salary, places=2,
                msg=slip.employee_id.name)

        # Виплата банком: Дт 661 (партнер-працівник) / Кт 311.
        pay_lines = []
        for slip in slips:
            partner = slip.employee_id.work_contact_id
            amount = round(slip.net_salary, 2)
            pay_lines += [
                (0, 0, {'account_id': self.acc_661.id,
                        'partner_id': partner.id,
                        'debit': amount, 'credit': 0.0,
                        'name': 'Виплата ЗП'}),
                (0, 0, {'account_id': self.acc_311.id,
                        'debit': 0.0, 'credit': amount,
                        'name': 'Виплата ЗП'}),
            ]
        payment = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': date(2025, 7, 5),
            'company_id': self.company.id,
            'line_ids': pay_lines,
        })
        payment.action_post()
        for slip in slips:
            self.assertAlmostEqual(
                self._balance_661(slip.employee_id.work_contact_id), 0.0,
                places=2, msg=slip.employee_id.name)
