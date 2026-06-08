"""Тести резерву відпусток — П(С)БО 26."""

from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestVacationReserve(TransactionCase):
    """Тести резерву відпусток."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1) or cls.env['account.journal'].create({
            'name': 'Test General',
            'code': 'TGEN',
            'type': 'general',
            'company_id': cls.company.id,
        })

        Account = cls.env['account.account']

        def _get_or_create(code, name, atype):
            acc = Account.search([
                ('code', '=', code),
                ('company_ids', 'in', cls.company.id),
            ], limit=1)
            if not acc:
                acc = Account.create({
                    'code': code,
                    'name': name,
                    'account_type': atype,
                    'company_ids': [(4, cls.company.id)],
                })
            return acc

        cls.acc_471 = _get_or_create('4711', 'Резерв відпусток', 'liability_current')
        cls.acc_661 = _get_or_create('6611', 'Розрахунки з персоналом', 'liability_payable')
        cls.acc_91 = _get_or_create('9111', 'Адмін. витрати', 'expense')
        cls.acc_23 = _get_or_create('2311', 'Виробництво', 'asset_current')

        # Configure company
        cls.company.write({
            'vacation_reserve_journal_id': cls.journal.id,
            'vacation_reserve_account_id': cls.acc_471.id,
            'vacation_payable_account_id': cls.acc_661.id,
            'vacation_reserve_default_expense_account_id': cls.acc_91.id,
            'vacation_reserve_annual_days': 24.0,
        })

        # Test employees
        cls.emp1 = cls.env['hr.employee'].create({
            'name': 'Тестова Іванна',
            'company_id': cls.company.id,
        })
        cls.emp2 = cls.env['hr.employee'].create({
            'name': 'Тестовий Петро',
            'company_id': cls.company.id,
        })

    def test_creation_sequence(self):
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
        })
        self.assertTrue(rec.name.startswith('РВ-'))
        self.assertEqual(rec.state, 'draft')
        # Defaults populated from company
        self.assertEqual(rec.journal_id, self.journal)
        self.assertEqual(rec.reserve_account_id, self.acc_471)

    def test_fill_lines(self):
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
        })
        rec.action_fill_lines()
        # We have created 2 test employees + may have demo ones
        emp_ids = rec.line_ids.mapped('employee_id.id')
        self.assertIn(self.emp1.id, emp_ids)
        self.assertIn(self.emp2.id, emp_ids)

    def test_days_accrued_computation(self):
        """31-day period × 24 / 365 ≈ 2.04 днів."""
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [(0, 0, {'employee_id': self.emp1.id})],
        })
        line = rec.line_ids
        # 24 * 31 / 365 = 2.03835... → 2.04
        self.assertAlmostEqual(line.days_accrued, 2.04, places=2)

    def test_expense_account_priority_company(self):
        """Без override на employee/job — береться company default."""
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [(0, 0, {'employee_id': self.emp1.id})],
        })
        self.assertEqual(rec.line_ids.expense_account_id, self.acc_91)

    def test_expense_account_priority_job(self):
        """Job override має пріоритет над company default."""
        job = self.env['hr.job'].create({
            'name': 'Виробничий працівник',
            'company_id': self.company.id,
            'vacation_reserve_expense_account_id': self.acc_23.id,
        })
        self.emp1.job_id = job
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [(0, 0, {'employee_id': self.emp1.id})],
        })
        self.assertEqual(rec.line_ids.expense_account_id, self.acc_23)

    def test_expense_account_priority_employee(self):
        """Employee override має найвищий пріоритет."""
        job = self.env['hr.job'].create({
            'name': 'Виробничий',
            'company_id': self.company.id,
            'vacation_reserve_expense_account_id': self.acc_23.id,
        })
        self.emp1.job_id = job
        self.emp1.vacation_reserve_expense_account_id = self.acc_91
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [(0, 0, {'employee_id': self.emp1.id})],
        })
        self.assertEqual(rec.line_ids.expense_account_id, self.acc_91)

    def test_confirm_creates_balanced_move(self):
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [
                (0, 0, {'employee_id': self.emp1.id, 'daily_average': 1000}),
                (0, 0, {'employee_id': self.emp2.id, 'daily_average': 1500}),
            ],
        })
        rec.action_confirm()
        self.assertEqual(rec.state, 'confirmed')
        self.assertTrue(rec.move_id)
        self.assertEqual(rec.move_id.state, 'posted')
        # Balance
        debit = sum(rec.move_id.line_ids.mapped('debit'))
        credit = sum(rec.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(debit, credit, places=2)
        # Кт 471 = sum of amounts
        kt_471 = rec.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_471)
        self.assertAlmostEqual(sum(kt_471.mapped('credit')), rec.total_amount, places=2)
        self.assertAlmostEqual(sum(kt_471.mapped('debit')), 0, places=2)

    def test_confirm_groups_by_expense_account(self):
        """Кілька працівників з тим самим рахунком — об'єднані в один Дт-рядок."""
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [
                (0, 0, {'employee_id': self.emp1.id, 'daily_average': 1000,
                        'expense_account_id': self.acc_91.id}),
                (0, 0, {'employee_id': self.emp2.id, 'daily_average': 1500,
                        'expense_account_id': self.acc_91.id}),
            ],
        })
        rec.action_confirm()
        # Усього 2 рядки в проводці: Дт 91 (агрегат) і Кт 471
        self.assertEqual(len(rec.move_id.line_ids), 2)

    def test_confirm_two_expense_accounts(self):
        """Два різні рахунки витрат — два Дт-рядки + один Кт."""
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [
                (0, 0, {'employee_id': self.emp1.id, 'daily_average': 1000,
                        'expense_account_id': self.acc_91.id}),
                (0, 0, {'employee_id': self.emp2.id, 'daily_average': 1500,
                        'expense_account_id': self.acc_23.id}),
            ],
        })
        rec.action_confirm()
        # 3 рядки: Дт 91, Дт 23, Кт 471
        self.assertEqual(len(rec.move_id.line_ids), 3)

    def test_cancel_cancels_move(self):
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [
                (0, 0, {'employee_id': self.emp1.id, 'daily_average': 1000}),
            ],
        })
        rec.action_confirm()
        move = rec.move_id
        rec.action_cancel()
        self.assertEqual(rec.state, 'cancelled')
        self.assertEqual(move.state, 'cancel')

    def test_confirm_requires_lines(self):
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
        })
        with self.assertRaises(UserError):
            rec.action_confirm()

    def test_zero_amount_line_skipped(self):
        """Рядок з нульовим середньоденним не створює рядка в move."""
        rec = self.env['hr.vacation.reserve'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 1, 31),
            'line_ids': [
                (0, 0, {'employee_id': self.emp1.id, 'daily_average': 0}),
                (0, 0, {'employee_id': self.emp2.id, 'daily_average': 1000}),
            ],
        })
        rec.action_confirm()
        # Тільки рядки з amount > 0 в проводці
        self.assertTrue(rec.move_id)
        debit = sum(rec.move_id.line_ids.mapped('debit'))
        credit = sum(rec.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(debit, credit, places=2)
