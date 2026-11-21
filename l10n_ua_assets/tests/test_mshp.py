"""МШП (рах. 22): передача в експлуатацію, забалансовий облік, списання (#204)."""

from datetime import date

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestMshp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Комірник Іван', 'company_id': cls.company.id})

        def acc(code, name, atype):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': atype,
                'company_ids': [(4, cls.company.id)]})
        cls.acc_expense = acc('9200M', 'Витрати МШП', 'expense')
        cls.acc_stock = acc('2200M', 'МШП', 'asset_current')
        cls.journal = cls.env['account.journal'].create({
            'name': 'МШП', 'type': 'general', 'code': 'MSHPJ',
            'company_id': cls.company.id})

    def _mshp(self, with_accounts=True, **kw):
        vals = {
            'name': 'Спецодяг', 'quantity': 5.0, 'unit_cost': 100.0,
            'employee_id': self.employee.id, 'company_id': self.company.id,
        }
        if with_accounts:
            vals.update({
                'journal_id': self.journal.id,
                'expense_account_id': self.acc_expense.id,
                'stock_account_id': self.acc_stock.id,
            })
        else:
            vals.update({
                'journal_id': False, 'expense_account_id': False,
                'stock_account_id': False,
            })
        vals.update(kw)
        return self.env['l10n_ua.mshp'].create(vals)

    def test_total_cost(self):
        rec = self._mshp()
        self.assertAlmostEqual(rec.total_cost, 500.0, places=2)

    def test_transfer_creates_move(self):
        rec = self._mshp()
        rec.action_transfer()
        self.assertEqual(rec.state, 'in_use')
        self.assertTrue(rec.transfer_number)
        self.assertTrue(rec.move_id)
        self.assertEqual(rec.move_id.state, 'posted')
        # Дт витрати 500 / Кт 22 500
        debit = rec.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_expense)
        credit = rec.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_stock)
        self.assertAlmostEqual(debit.debit, 500.0, places=2)
        self.assertAlmostEqual(credit.credit, 500.0, places=2)

    def test_transfer_register_only_without_accounts(self):
        rec = self._mshp(with_accounts=False)
        rec.action_transfer()
        self.assertEqual(rec.state, 'in_use')
        self.assertTrue(rec.transfer_number)
        # Без рахунків проводка не створюється (лише забалансовий облік)
        self.assertFalse(rec.move_id)

    def test_write_off(self):
        rec = self._mshp()
        rec.action_transfer()
        rec.writeoff_reason = 'Зношено'
        rec.action_write_off()
        self.assertEqual(rec.state, 'written_off')
        self.assertTrue(rec.writeoff_act_number)
        self.assertTrue(rec.writeoff_date)

    def test_write_off_requires_in_use(self):
        rec = self._mshp()
        with self.assertRaises(UserError):
            rec.action_write_off()

    def test_draft_reverses_move(self):
        rec = self._mshp()
        rec.action_transfer()
        move = rec.move_id
        rec.action_draft()
        self.assertEqual(rec.state, 'draft')
        self.assertFalse(rec.move_id)
        # Створено сторнуючу проводку, що нейтралізує первісну
        reversal = self.env['account.move'].search(
            [('reversed_entry_id', '=', move.id)])
        self.assertTrue(reversal, 'Має бути сторнуюча проводка')

    def test_register_only_in_use(self):
        # Реєстр = записи в стані in_use
        rec = self._mshp()
        rec.action_transfer()
        in_use = self.env['l10n_ua.mshp'].search([('state', '=', 'in_use')])
        self.assertIn(rec, in_use)

    # --- #626: дата документа списання ---

    def test_write_off_uses_document_date(self):
        rec = self._mshp(date=date(2025, 3, 1))
        self.assertEqual(rec.document_date, fields.Date.context_today(rec))
        rec.action_transfer()
        self.assertEqual(rec.move_id.date, date(2025, 3, 1))
        self.assertFalse(rec.document_date)
        rec.document_date = date(2025, 10, 15)
        rec.action_write_off()
        self.assertEqual(rec.writeoff_date, date(2025, 10, 15))

    def test_write_off_without_document_date_is_today(self):
        rec = self._mshp(date=date(2025, 3, 1))
        rec.action_transfer()
        rec.action_write_off()
        self.assertEqual(rec.writeoff_date, fields.Date.context_today(rec))

    def test_write_off_before_transfer_raises(self):
        rec = self._mshp(date=date(2025, 3, 1))
        rec.action_transfer()
        rec.document_date = date(2025, 2, 1)
        with self.assertRaises(UserError):
            rec.action_write_off()
