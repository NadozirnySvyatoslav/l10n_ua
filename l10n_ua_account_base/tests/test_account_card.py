"""Тести картки рахунку (#131).

Покриття:
- Початкове сальдо (рух до періоду) + наростаючий залишок + кінцеве сальдо
- Хронологічний рух, кореспондуючий рахунок
- Виключення поза періодом / draft
- Фільтр за партнером (субконто)
- Валідація періоду
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountCard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Контрагент КР'})
        cls.partner2 = cls.env['res.partner'].create({
            'name': 'ТОВ Другий КР'})
        cls.journal = cls.env['account.journal'].create({
            'name': 'Картка тест', 'code': 'ACRD',
            'type': 'general', 'company_id': cls.company.id})
        cls.acc_a = cls.env['account.account'].create({
            'name': 'КР рахунок', 'code': 'ACRDA',
            'account_type': 'asset_current',
            'company_ids': [(4, cls.company.id)]})
        cls.acc_b = cls.env['account.account'].create({
            'name': 'КР корресп', 'code': 'ACRDB',
            'account_type': 'income',
            'company_ids': [(4, cls.company.id)]})

    def _move(self, move_date, debit_acc, credit_acc, amount, partner=None, post=True):
        partner = partner or self.partner
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [
                (0, 0, {'account_id': debit_acc.id, 'partner_id': partner.id,
                        'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': credit_acc.id, 'partner_id': partner.id,
                        'debit': 0.0, 'credit': amount}),
            ],
        })
        if post:
            move.action_post()
        return move

    def _card(self, partner=None):
        return self.env['l10n_ua.account.card'].create({
            'account_id': self.acc_a.id,
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'company_id': self.company.id,
            'partner_id': partner.id if partner else False,
        })

    def test_opening_running_closing(self):
        # До періоду: Дт acc_a 1000 → початкове сальдо 1000.
        self._move(date(2024, 12, 31), self.acc_a, self.acc_b, 1000.0)
        # У періоді: Дт acc_a 500, потім Кт acc_a 200.
        self._move(date(2025, 3, 1), self.acc_a, self.acc_b, 500.0)
        self._move(date(2025, 6, 1), self.acc_b, self.acc_a, 200.0)
        # Після періоду — ігнорується.
        self._move(date(2026, 1, 5), self.acc_a, self.acc_b, 999.0)

        card = self._card()
        card.action_compute()

        self.assertAlmostEqual(card.opening_balance, 1000.0)
        self.assertEqual(len(card.line_ids), 2)
        self.assertAlmostEqual(card.total_debit, 500.0)
        self.assertAlmostEqual(card.total_credit, 200.0)
        self.assertAlmostEqual(card.closing_balance, 1300.0)

        # Наростаючий залишок і хронологія.
        l1, l2 = card.line_ids.sorted('date')
        self.assertAlmostEqual(l1.debit, 500.0)
        self.assertAlmostEqual(l1.running_balance, 1500.0)
        self.assertAlmostEqual(l2.credit, 200.0)
        self.assertAlmostEqual(l2.running_balance, 1300.0)
        # Кореспондуючий рахунок — з протилежного боку.
        self.assertEqual(l1.corr_account_id, self.acc_b)
        self.assertEqual(l2.corr_account_id, self.acc_b)

    def test_draft_excluded(self):
        self._move(date(2025, 5, 5), self.acc_a, self.acc_b, 333.0, post=False)
        card = self._card()
        card.action_compute()
        self.assertFalse(card.line_ids)
        self.assertAlmostEqual(card.opening_balance, 0.0)

    def test_partner_subconto_filter(self):
        self._move(date(2025, 4, 1), self.acc_a, self.acc_b, 100.0, partner=self.partner)
        self._move(date(2025, 4, 2), self.acc_a, self.acc_b, 60.0, partner=self.partner2)

        card = self._card(partner=self.partner)
        card.action_compute()
        self.assertEqual(len(card.line_ids), 1)
        self.assertAlmostEqual(card.total_debit, 100.0)
        self.assertEqual(card.line_ids.partner_id, self.partner)

    def test_period_validation(self):
        card = self.env['l10n_ua.account.card'].create({
            'account_id': self.acc_a.id,
            'period_start': date(2025, 12, 31),
            'period_end': date(2025, 1, 1),
            'company_id': self.company.id,
        })
        with self.assertRaises(UserError):
            card.action_compute()
