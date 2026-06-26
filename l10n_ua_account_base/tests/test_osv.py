"""Tests for OSV (Оборотно-сальдова відомість / Trial Balance).

Tests cover:
- action_compute() builds lines from posted moves only
- Opening balance from movements before the period
- Period turnover (debit/credit) and closing balance netting
- Synthetic (by account) vs analytic (by account + partner) grouping
- Total turnover debit == total turnover credit (double-entry sanity)
- Period validation errors
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestOsv(TransactionCase):
    """Test the Trial Balance / OSV computation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.partner = cls.env['res.partner'].create({
            'name': 'ТОВ Контрагент ОСВ',
            'company_type': 'company',
        })
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'Разні ОСВ',
                'code': 'OSVT',
                'type': 'general',
                'company_id': cls.company.id,
            })
        cls.acc_a = cls.env['account.account'].create({
            'name': 'ОСВ актив',
            'code': 'OSVA1',
            'account_type': 'asset_current',
            'company_ids': [(4, cls.company.id)],
        })
        cls.acc_b = cls.env['account.account'].create({
            'name': 'ОСВ дохід',
            'code': 'OSVB1',
            'account_type': 'income',
            'company_ids': [(4, cls.company.id)],
        })

    def _post_move(self, move_date, amount, partner=None):
        """Post a balanced entry: Dr acc_a / Cr acc_b for ``amount``."""
        partner = partner or self.partner
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': move_date,
            'line_ids': [
                (0, 0, {
                    'account_id': self.acc_a.id,
                    'partner_id': partner.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': self.acc_b.id,
                    'partner_id': partner.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _create_osv(self, osv_type='synthetic'):
        return self.env['l10n_ua.osv'].create({
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'osv_type': osv_type,
            'company_id': self.company.id,
        })

    def _line_for(self, osv, account, partner=None):
        lines = osv.line_ids.filtered(lambda l: l.account_id == account)
        if partner is not None:
            lines = lines.filtered(lambda l: l.partner_id == partner)
        return lines

    def test_synthetic_opening_turnover_closing(self):
        """Opening from prior moves, period turnover and netted closing."""
        # Opening: posted before the period.
        self._post_move(date(2024, 12, 31), 1000.0)
        # Turnover: inside the period.
        self._post_move(date(2025, 6, 15), 500.0)
        # Outside the period (after end) — must be ignored.
        self._post_move(date(2026, 1, 10), 999.0)

        osv = self._create_osv('synthetic')
        osv.action_compute()

        line_a = self._line_for(osv, self.acc_a)
        line_b = self._line_for(osv, self.acc_b)
        self.assertEqual(len(line_a), 1)
        self.assertEqual(len(line_b), 1)

        # Asset side (debit account).
        self.assertAlmostEqual(line_a.opening_debit, 1000.0)
        self.assertAlmostEqual(line_a.opening_credit, 0.0)
        self.assertAlmostEqual(line_a.turnover_debit, 500.0)
        self.assertAlmostEqual(line_a.turnover_credit, 0.0)
        self.assertAlmostEqual(line_a.closing_debit, 1500.0)
        self.assertAlmostEqual(line_a.closing_credit, 0.0)

        # Income side (credit account) — mirror.
        self.assertAlmostEqual(line_b.opening_credit, 1000.0)
        self.assertAlmostEqual(line_b.opening_debit, 0.0)
        self.assertAlmostEqual(line_b.turnover_credit, 500.0)
        self.assertAlmostEqual(line_b.closing_credit, 1500.0)

    def test_turnover_is_balanced(self):
        """Double-entry: total turnover debit equals total turnover credit.

        The whole company is summed (the DB may already hold other posted
        moves), so the invariant checked here is the global balance; the exact
        950 contribution is verified on this test's own accounts.
        """
        self._post_move(date(2025, 3, 1), 700.0)
        self._post_move(date(2025, 9, 1), 250.0)

        osv = self._create_osv('synthetic')
        osv.action_compute()

        total_debit = sum(osv.line_ids.mapped('turnover_debit'))
        total_credit = sum(osv.line_ids.mapped('turnover_credit'))
        self.assertAlmostEqual(total_debit, total_credit)

        self.assertAlmostEqual(self._line_for(osv, self.acc_a).turnover_debit, 950.0)
        self.assertAlmostEqual(self._line_for(osv, self.acc_b).turnover_credit, 950.0)

    def test_draft_moves_excluded(self):
        """Unposted (draft) moves must not appear in the OSV."""
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal.id,
            'date': date(2025, 5, 5),
            'line_ids': [
                (0, 0, {'account_id': self.acc_a.id, 'debit': 333.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.acc_b.id, 'debit': 0.0, 'credit': 333.0}),
            ],
        })
        self.assertEqual(move.state, 'draft')

        osv = self._create_osv('synthetic')
        osv.action_compute()
        self.assertFalse(self._line_for(osv, self.acc_a))

    def test_analytic_groups_by_partner(self):
        """Analytic OSV splits the same account across partners."""
        partner2 = self.env['res.partner'].create({
            'name': 'ТОВ Другий ОСВ',
            'company_type': 'company',
        })
        self._post_move(date(2025, 4, 1), 100.0, partner=self.partner)
        self._post_move(date(2025, 4, 2), 60.0, partner=partner2)

        osv = self._create_osv('analytic')
        osv.action_compute()

        a_p1 = self._line_for(osv, self.acc_a, self.partner)
        a_p2 = self._line_for(osv, self.acc_a, partner2)
        self.assertEqual(len(a_p1), 1)
        self.assertEqual(len(a_p2), 1)
        self.assertAlmostEqual(a_p1.turnover_debit, 100.0)
        self.assertAlmostEqual(a_p2.turnover_debit, 60.0)

    def test_period_validation(self):
        """Missing or reversed period raises a user error."""
        osv = self.env['l10n_ua.osv'].create({
            'period_start': date(2025, 12, 31),
            'period_end': date(2025, 1, 1),
            'osv_type': 'synthetic',
            'company_id': self.company.id,
        })
        with self.assertRaises(UserError):
            osv.action_compute()
