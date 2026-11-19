"""Утримання авансу не проводиться Дт 661 Кт 685 (#574).

Аванс уже зменшив 661 при виплаті (Дт 661 Кт 301/311). Якщо утримання
авансу в листку піде ще й «Іншими утриманнями» Дт 661 Кт 685, рахунок 661
зменшиться вдруге, а на 685 зʼявиться фіктивний борг.
"""

from datetime import date

from odoo.tests import tagged
from odoo.addons.l10n_ua_hr_salary.tests.common import SalaryTestCase


@tagged('post_install', '-at_install')
class TestAdvanceNotPostedTo685(SalaryTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def acc(code, name, atype):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': atype,
                'company_ids': [(4, cls.company.id)]})
        cls.acc_expense = acc('9200V', 'Адмінвитрати ЗП', 'expense')
        cls.acc_661 = acc('6610V', 'ЗП до виплати', 'liability_payable')
        cls.acc_651 = acc('6510V', 'ЄСВ', 'liability_current')
        cls.acc_6411 = acc('6411V', 'ПДФО', 'liability_current')
        cls.acc_6415 = acc('6415V', 'Військовий збір', 'liability_current')
        cls.acc_685 = acc('6850V', 'Інші кредитори', 'liability_current')

        cls.journal = cls.env['account.journal'].create({
            'name': 'Зарплата', 'type': 'general', 'code': 'SALV',
            'company_id': cls.company.id})

        cfg_vals = {
            'salary_journal_id': cls.journal.id,
            'wages_payable_account_id': cls.acc_661.id,
            'pdfo_payable_account_id': cls.acc_6411.id,
            'military_tax_payable_account_id': cls.acc_6415.id,
            'esv_payable_account_id': cls.acc_651.id,
            'other_payable_account_id': cls.acc_685.id,
            'default_expense_account_id': cls.acc_expense.id,
        }
        cls.config = cls.env['hr.salary.account.config'].search(
            [('company_id', '=', cls.company.id)], limit=1)
        if cls.config:
            cls.config.write(cfg_vals)
        else:
            cls.config = cls.env['hr.salary.account.config'].create(
                dict(cfg_vals, company_id=cls.company.id))

        cls.type_advance = cls.env.ref(
            'l10n_ua_hr_salary.deduction_type_advance')
        cls.type_alimony = cls.env.ref(
            'l10n_ua_hr_salary.deduction_type_alimony')

    def _slip(self, advance=0.0, alimony=0.0):
        slip = self.env['hr.payslip'].create({
            'employee_id': self.employee.id,
            'version_id': self.version.id,
            'date_from': date(2025, 6, 1),
            'date_to': date(2025, 6, 30),
        })
        slip.write({
            'scheduled_hours': 160.0, 'scheduled_days': 20,
            'worked_days': 20, 'worked_hours': 160.0,
        })
        slip.action_compute_sheet()
        vals = []
        if advance:
            vals.append({'deduction_type_id': self.type_advance.id,
                         'amount': advance})
        if alimony:
            vals.append({'deduction_type_id': self.type_alimony.id,
                         'amount': alimony})
        if vals:
            slip.write({'deduction_ids': [(0, 0, v) for v in vals]})
        self.assertTrue(slip.gross_salary, 'Має бути ненульове нарахування')
        return slip

    def _sum(self, lines, account, side):
        return round(sum(l[side] for l in lines
                         if l['account_id'] == account.id), 2)

    def test_net_salary_still_reduced_by_advance(self):
        """«До виплати» як і раніше зменшується на аванс."""
        slip = self._slip(advance=8000.0)
        self.assertEqual(slip.advance_amount, 8000.0)
        self.assertAlmostEqual(
            slip.net_salary,
            slip.gross_salary - slip.pdfo_amount
            - slip.military_tax_amount - 8000.0, places=2)

    def test_per_payslip_no_685_for_advance(self):
        slip = self._slip(advance=8000.0)
        lines = slip._prepare_move_lines(self.config)
        self.assertFalse(
            [l for l in lines if l['account_id'] == self.acc_685.id],
            'Аванс не має йти Дт 661 Кт 685')
        # Дт 661 — лише ПДФО і ВЗ; сальдо 661 перед остаточною виплатою
        # з урахуванням виплаченого авансу дорівнює «До виплати».
        debit_661 = self._sum(lines, self.acc_661, 'debit')
        self.assertAlmostEqual(
            debit_661, slip.pdfo_amount + slip.military_tax_amount, places=2)
        credit_661 = self._sum(lines, self.acc_661, 'credit')
        self.assertAlmostEqual(
            credit_661 - debit_661 - 8000.0, slip.net_salary, places=2)

    def test_per_payslip_other_deduction_still_685(self):
        """Аліменти поруч з авансом далі йдуть Дт 661 Кт 685 — без авансу."""
        slip = self._slip(advance=8000.0, alimony=1500.0)
        lines = slip._prepare_move_lines(self.config)
        self.assertEqual(self._sum(lines, self.acc_685, 'credit'), 1500.0)
        debit_661 = self._sum(lines, self.acc_661, 'debit')
        self.assertAlmostEqual(
            debit_661,
            slip.pdfo_amount + slip.military_tax_amount + 1500.0, places=2)

    def test_per_batch_no_685_for_advance(self):
        slip = self._slip(advance=8000.0, alimony=1500.0)
        run = self.env['hr.payslip.run'].create({
            'name': 'Червень 2025',
            'date_start': date(2025, 6, 1),
            'date_end': date(2025, 6, 30),
            'company_id': self.company.id,
        })
        slip.write({'payslip_run_id': run.id, 'state': 'done'})
        run._create_consolidated_move(self.config)
        self.assertTrue(run.move_id)
        lines = run.move_id.line_ids
        credit_685 = sum(lines.filtered(
            lambda l: l.account_id == self.acc_685).mapped('credit'))
        self.assertAlmostEqual(credit_685, 1500.0, places=2)
        debit_661 = sum(lines.filtered(
            lambda l: l.account_id == self.acc_661).mapped('debit'))
        self.assertAlmostEqual(
            debit_661,
            slip.pdfo_amount + slip.military_tax_amount + 1500.0, places=2)
