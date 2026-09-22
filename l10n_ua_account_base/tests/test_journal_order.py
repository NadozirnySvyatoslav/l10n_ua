"""Тести журналу-ордера (#130).

Покриття:
- action_compute наповнює рядки з posted-проводок обраного журналу/періоду
- Проводки поза періодом (до/після) ігноруються
- Чернеткові (draft) проводки ігноруються
- Проводки іншого журналу не потрапляють
- Підсумки total_debit / total_credit; поля рядка
- Валідація періоду
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestJournalOrder(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Контрагент ЖО'})
        # Власний журнал — щоб у ньому були лише проводки цього тесту.
        cls.journal = cls.env['account.journal'].create({
            'name': 'Журнал-ордер тест', 'code': 'JOT',
            'type': 'general', 'company_id': cls.company.id})
        cls.other_journal = cls.env['account.journal'].create({
            'name': 'Інший журнал', 'code': 'JOT2',
            'type': 'general', 'company_id': cls.company.id})
        cls.acc_a = cls.env['account.account'].create({
            'name': 'ЖО актив', 'code': 'JOA1',
            'account_type': 'asset_current',
            'company_ids': [(4, cls.company.id)]})
        cls.acc_b = cls.env['account.account'].create({
            'name': 'ЖО дохід', 'code': 'JOB1',
            'account_type': 'income',
            'company_ids': [(4, cls.company.id)]})

    def _move(self, move_date, amount, journal=None, post=True):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': (journal or self.journal).id,
            'date': move_date,
            'line_ids': [
                (0, 0, {'account_id': self.acc_a.id, 'partner_id': self.partner.id,
                        'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': self.acc_b.id, 'partner_id': self.partner.id,
                        'debit': 0.0, 'credit': amount}),
            ],
        })
        if post:
            move.action_post()
        return move

    def _create_jo(self):
        return self.env['l10n_ua.journal.order'].create({
            'journal_id': self.journal.id,
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'company_id': self.company.id,
        })

    def test_compute_fills_lines_from_posted_moves(self):
        m = self._move(date(2025, 6, 15), 500.0)
        jo = self._create_jo()
        jo.action_compute()

        # Одна проводка = 2 рядки (Дт acc_a / Кт acc_b).
        self.assertEqual(len(jo.line_ids), 2)
        debit_line = jo.line_ids.filtered(lambda l: l.account_id == self.acc_a)
        credit_line = jo.line_ids.filtered(lambda l: l.account_id == self.acc_b)
        self.assertAlmostEqual(debit_line.debit, 500.0)
        self.assertAlmostEqual(credit_line.credit, 500.0)
        self.assertEqual(debit_line.partner_id, self.partner)
        self.assertEqual(debit_line.move_id, m)
        self.assertEqual(debit_line.date, date(2025, 6, 15))
        self.assertAlmostEqual(jo.total_debit, 500.0)
        self.assertAlmostEqual(jo.total_credit, 500.0)

    def test_out_of_period_excluded(self):
        self._move(date(2024, 12, 31), 100.0)   # до періоду
        self._move(date(2026, 1, 10), 200.0)     # після періоду
        self._move(date(2025, 3, 1), 300.0)      # у періоді
        jo = self._create_jo()
        jo.action_compute()
        self.assertEqual(len(jo.line_ids), 2)
        self.assertAlmostEqual(jo.total_debit, 300.0)

    def test_draft_excluded(self):
        self._move(date(2025, 5, 5), 333.0, post=False)
        jo = self._create_jo()
        jo.action_compute()
        self.assertFalse(jo.line_ids)

    def test_other_journal_excluded(self):
        self._move(date(2025, 4, 1), 400.0, journal=self.other_journal)
        self._move(date(2025, 4, 2), 150.0)  # наш журнал
        jo = self._create_jo()
        jo.action_compute()
        self.assertEqual(len(jo.line_ids), 2)
        self.assertAlmostEqual(jo.total_debit, 150.0)

    def test_recompute_replaces_lines(self):
        self._move(date(2025, 2, 2), 250.0)
        jo = self._create_jo()
        jo.action_compute()
        jo.action_compute()  # повторно — без дублів
        self.assertEqual(len(jo.line_ids), 2)

    def test_period_validation(self):
        jo = self.env['l10n_ua.journal.order'].create({
            'journal_id': self.journal.id,
            'period_start': date(2025, 12, 31),
            'period_end': date(2025, 1, 1),
            'company_id': self.company.id,
        })
        with self.assertRaises(UserError):
            jo.action_compute()
