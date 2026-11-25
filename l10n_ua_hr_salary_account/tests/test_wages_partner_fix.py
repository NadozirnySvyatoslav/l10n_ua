"""Майстер «партнер 661/685 у старих проводках ЗП» (ADR 0003, #588).

Стару проводку імітуємо так: створюємо штатну і знімаємо партнера з рядків
661/685 — так виглядали проводки до #592.
"""

from datetime import date

from odoo.tests import tagged

from .test_wages_partner import TestWagesPartner


@tagged('post_install', '-at_install')
class TestWagesPartnerFix(TestWagesPartner):

    def _make_legacy(self, move):
        move.button_draft()
        move.line_ids.filtered(
            lambda l: l.account_id in (self.acc_661 | self.acc_685)
        ).write({'partner_id': False})
        move.action_post()

    def _legacy_lines(self, move):
        return move.line_ids.filtered(
            lambda l: l.account_id in (self.acc_661 | self.acc_685)
            and not l.partner_id)

    def _wizard(self):
        return self.env['hr.salary.wages.partner.fix'].create({
            'company_id': self.company.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 12, 31),
        })

    def _totals(self, move):
        res = {}
        for line in move.line_ids:
            res[line.account_id.id] = round(
                res.get(line.account_id.id, 0.0) + line.balance, 2)
        return res

    def _legacy_run(self):
        self.config.entry_granularity = 'per_batch'
        run, slips = self._closed_run()
        self._make_legacy(run.move_id)
        self.assertTrue(self._legacy_lines(run.move_id))
        return run, slips

    def _legacy_slip(self):
        self.config.entry_granularity = 'per_payslip'
        emp, version = self.employees[0]
        slip = self._slip(emp, version, alimony=1000.0)
        slip.state = 'done'
        slip._create_account_move(self.config)
        self._make_legacy(slip.move_id)
        self.assertTrue(self._legacy_lines(slip.move_id))
        return slip

    # --- per payslip ---------------------------------------------------

    def test_per_payslip_sets_partner_amounts_unchanged(self):
        slip = self._legacy_slip()
        move = slip.move_id
        before = self._totals(move)
        wiz = self._wizard()
        wiz.action_preview()
        self.assertIn('OK', wiz.summary)
        self.assertTrue(self._legacy_lines(move), 'Перегляд нічого не змінює')

        wiz.action_apply()
        self.assertEqual(slip.move_id, move, 'Проводка листка та сама')
        self.assertFalse(self._legacy_lines(move))
        self.assertEqual(
            set(move.line_ids.filtered(
                lambda l: l.account_id in (self.acc_661 | self.acc_685)
            ).partner_id), {slip.employee_id.work_contact_id})
        self.assertEqual(self._totals(move), before)

    # --- per batch -----------------------------------------------------

    def test_per_batch_rebuild_line_per_employee(self):
        run, slips = self._legacy_run()
        old = run.move_id
        before = self._totals(old)

        wiz = self._wizard()
        wiz.action_preview()
        self.assertEqual(run.move_id, old, 'Перегляд нічого не змінює')
        self.assertEqual(old.state, 'posted')

        wiz.action_apply()
        new = run.move_id
        self.assertNotEqual(new, old)
        self.assertEqual(new.date, old.date)
        self.assertEqual(new.state, 'posted')
        self.assertFalse(self._legacy_lines(new))
        self.assertEqual(self._totals(new), before)
        # Стару сторновано тією ж датою.
        reversal = self.env['account.move'].search(
            [('reversed_entry_id', '=', old.id)])
        self.assertEqual(reversal.date, old.date)
        self.assertEqual(reversal.state, 'posted')
        # Сальдо 661 по працівнику = його «до виплати».
        for slip in slips:
            self.assertAlmostEqual(
                -self._balance_661(slip.employee_id.work_contact_id),
                slip.net_salary, places=2, msg=slip.employee_id.name)
        self.assertTrue(run.message_ids.filtered(
            lambda m: 'ADR 0003' in (m.body or '')))

    def test_second_run_changes_nothing(self):
        run, _slips = self._legacy_run()
        slip = self._legacy_slip()
        self._wizard().action_apply()
        run_move, slip_move = run.move_id, slip.move_id
        n_moves = self.env['account.move'].search_count([])

        wiz = self._wizard()
        wiz.action_apply()
        self.assertEqual(run.move_id, run_move)
        self.assertEqual(slip.move_id, slip_move)
        self.assertEqual(self.env['account.move'].search_count([]), n_moves)
        self.assertIn('листків 0, пакетів 0', wiz.summary)

    # --- закриті періоди ----------------------------------------------

    def test_locked_period_refused(self):
        run, _slips = self._legacy_run()
        slip = self._legacy_slip()
        old = run.move_id
        self.company.fiscalyear_lock_date = date(2025, 6, 30)

        wiz = self._wizard()
        wiz.action_apply()
        self.assertEqual(run.move_id, old)
        self.assertTrue(self._legacy_lines(old))
        self.assertTrue(self._legacy_lines(slip.move_id))
        self.assertIn('закритий період', wiz.summary)
        self.assertFalse(self.env['account.move'].search(
            [('reversed_entry_id', '=', old.id)]))

    def test_reconciled_batch_refused(self):
        run, slips = self._legacy_run()
        old = run.move_id
        # Виплата, звірена з рядком 661 старої проводки.
        line_661 = old.line_ids.filtered(
            lambda l: l.account_id == self.acc_661 and l.credit)[:1]
        pay = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': date(2025, 7, 5),
            'company_id': self.company.id,
            'line_ids': [
                (0, 0, {'account_id': self.acc_661.id, 'debit': 100.0,
                        'credit': 0.0, 'name': 'Виплата'}),
                (0, 0, {'account_id': self.acc_311.id, 'debit': 0.0,
                        'credit': 100.0, 'name': 'Виплата'}),
            ],
        })
        pay.action_post()
        (line_661 | pay.line_ids.filtered(
            lambda l: l.account_id == self.acc_661)).reconcile()

        wiz = self._wizard()
        wiz.action_apply()
        self.assertEqual(run.move_id, old)
        self.assertIn('звірені', wiz.summary)

    def test_changed_accounts_refused(self):
        """Якщо налаштування рахунків змінились — пакет не чіпаємо."""
        run, _slips = self._legacy_run()
        old = run.move_id
        other = self.env['account.account'].create({
            'code': '9300P', 'name': 'Збут', 'account_type': 'expense',
            'company_ids': [(4, self.company.id)]})
        self.config.default_expense_account_id = other

        wiz = self._wizard()
        wiz.action_apply()
        self.assertEqual(run.move_id, old)
        self.assertEqual(old.state, 'posted')
        self.assertFalse(self.env['account.move'].search(
            [('reversed_entry_id', '=', old.id)]))
        self.assertIn('не збігається', wiz.summary)
