"""Тести взаєморозрахунків з ПФУ (#157, #499)."""

from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestFssSettlement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Хворий Іван', 'company_id': cls.company.id})

    def _sick_leave(self, dfrom, dto):
        sl = self.env['hr.sick.leave'].create({
            'employee_id': self.employee.id,
            'company_id': self.company.id,
            'date_from': dfrom, 'date_to': dto,
            'sick_leave_type': 'illness',
            'insurance_experience_years': 10.0,
            'average_daily_salary': 500.0,
        })
        return sl

    def _settlement(self):
        return self.env['hr.fss.settlement'].create({
            'company_id': self.company.id,
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 31)})

    def test_gather_and_accrued(self):
        sl = self._sick_leave(date(2026, 1, 10), date(2026, 1, 20))  # 11 днів → ПФУ 6
        self.assertGreater(sl.fss_amount, 0)
        st = self._settlement()
        st.action_gather_sick_leaves()
        self.assertIn(sl, st.sick_leave_ids)
        self.assertAlmostEqual(st.amount_accrued, sl.fss_amount, places=2)
        self.assertAlmostEqual(st.residual, sl.fss_amount, places=2)

    def test_submit_state(self):
        self._sick_leave(date(2026, 1, 10), date(2026, 1, 20))
        st = self._settlement()
        st.action_gather_sick_leaves()
        st.action_submit()
        self.assertEqual(st.state, 'submitted')
        self.assertTrue(st.date_submitted)

    def test_partial_and_full_reimbursement(self):
        sl = self._sick_leave(date(2026, 1, 10), date(2026, 1, 20))
        st = self._settlement()
        st.action_gather_sick_leaves()
        st.action_submit()
        accrued = st.amount_accrued
        # Часткове відшкодування.
        st.amount_received = accrued - 100.0
        st.action_register_reimbursement()
        self.assertEqual(st.state, 'partial')
        self.assertAlmostEqual(st.residual, 100.0, places=2)
        # Повне.
        st.amount_received = accrued
        self.assertEqual(st.state, 'reimbursed')
        self.assertAlmostEqual(st.residual, 0.0, places=2)

    def test_storno_unreimbursed(self):
        self._sick_leave(date(2026, 1, 10), date(2026, 1, 20))
        st = self._settlement()
        st.action_gather_sick_leaves()
        st.action_submit()
        st.amount_received = st.amount_accrued - 300.0  # 300 не відшкодовано
        st.action_register_reimbursement()
        journal = self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.company.id)],
            limit=1)
        accounts = self.env['account.account'].search(
            [('company_ids', 'in', self.company.id)], limit=2)
        st.write({
            'journal_id': journal.id,
            'expense_account_id': accounts[0].id,
            'fss_receivable_account_id': accounts[1].id,
        })
        st.action_write_off_unreimbursed()
        self.assertEqual(st.state, 'written_off')
        self.assertTrue(st.storno_move_id)
        self.assertAlmostEqual(
            sum(st.storno_move_id.line_ids.mapped('debit')), 300.0, places=2)

    def test_storno_requires_accounts(self):
        self._sick_leave(date(2026, 1, 10), date(2026, 1, 20))
        st = self._settlement()
        st.action_gather_sick_leaves()
        st.amount_received = 100.0
        with self.assertRaises(UserError):
            st.action_write_off_unreimbursed()
