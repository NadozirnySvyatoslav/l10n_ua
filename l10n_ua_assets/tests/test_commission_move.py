"""Проводка введення ОЗ в експлуатацію Дт 10х / Кт 152 — issue #628."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCommissionMove(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.journal = cls.env['account.journal'].create({
            'name': 'ОЗ тест', 'code': 'OZCM', 'type': 'general',
            'company_id': cls.company.id,
        })

        def acc(code, name, account_type):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': account_type,
                'company_ids': [(4, cls.company.id)],
            })

        cls.acc_104 = acc('104900', 'Машини та обладнання', 'asset_fixed')
        cls.acc_106 = acc('106900', 'Інструменти', 'asset_fixed')
        cls.acc_152 = acc('152900', 'Придбання ОЗ', 'asset_non_current')
        cls.acc_expense = acc('923900', 'Амортизація', 'expense')
        cls.acc_131 = acc('131900', 'Знос ОЗ', 'asset_fixed')

        cls.group = cls.env['l10n_ua.asset.group'].create({
            'code': 'CM-ON',
            'name': 'Група з проводкою введення',
            'min_useful_life': 5,
            'depreciation_journal_id': cls.journal.id,
            'expense_account_id': cls.acc_expense.id,
            'depreciation_account_id': cls.acc_131.id,
            'create_commission_move': True,
            'fixed_asset_account_id': cls.acc_104.id,
            'commission_account_id': cls.acc_152.id,
        })
        cls.group_off = cls.env['l10n_ua.asset.group'].create({
            'code': 'CM-OFF',
            'name': 'Група без проводки введення',
            'min_useful_life': 5,
            'depreciation_journal_id': cls.journal.id,
            'fixed_asset_account_id': cls.acc_104.id,
            'commission_account_id': cls.acc_152.id,
        })

    def _asset(self, **kw):
        vals = {
            'name': 'Верстат',
            'acquisition_date': date(2025, 10, 10),
            'commission_date': date(2025, 10, 31),
            'original_value': 48000,
            'useful_life': 60,
            'group_id': self.group.id,
            'company_id': self.company.id,
        }
        vals.update(kw)
        return self.env['l10n_ua.asset'].create(vals)

    def test_commission_creates_move(self):
        asset = self._asset()
        asset.action_commission()
        move = asset.commission_move_id
        self.assertTrue(move)
        self.assertEqual(move.state, 'posted')
        self.assertEqual(move.date, date(2025, 10, 31))
        self.assertEqual(move.journal_id, self.journal)
        debit = move.line_ids.filtered(lambda l: l.account_id == self.acc_104)
        credit = move.line_ids.filtered(lambda l: l.account_id == self.acc_152)
        self.assertAlmostEqual(debit.debit, 48000, places=2)
        self.assertAlmostEqual(credit.credit, 48000, places=2)
        self.assertIn(asset.commission_act_number, move.ref)

    def test_asset_override_wins(self):
        asset = self._asset(fixed_asset_account_id=self.acc_106.id)
        asset.action_commission()
        debit = asset.commission_move_id.line_ids.filtered(lambda l: l.debit)
        self.assertEqual(debit.account_id, self.acc_106)

    def test_group_flag_off_no_move(self):
        asset = self._asset(group_id=self.group_off.id)
        asset.action_commission()
        self.assertEqual(asset.state, 'open')
        self.assertFalse(asset.commission_move_id)

    def test_asset_opt_out_no_move(self):
        asset = self._asset(no_commission_move=True)
        asset.action_commission()
        self.assertEqual(asset.state, 'open')
        self.assertFalse(asset.commission_move_id)

    def test_missing_accounts_raise(self):
        self.group.commission_account_id = False
        asset = self._asset()
        with self.assertRaises(UserError):
            asset.action_commission()

    def test_draft_removes_move_and_recommission(self):
        asset = self._asset()
        asset.action_commission()
        move = asset.commission_move_id
        asset.action_draft()
        self.assertFalse(asset.commission_move_id)
        self.assertFalse(move.exists())
        asset.commission_date = date(2025, 11, 3)
        asset.action_commission()
        self.assertTrue(asset.commission_move_id)
        self.assertEqual(asset.commission_move_id.date, date(2025, 11, 3))

    def test_commission_and_depreciation_share_journal(self):
        """Проводка введення і амортизація — в одному журналі; 10х/131
        разом дають залишкову вартість."""
        asset = self._asset()
        asset.action_commission()
        asset.action_compute_depreciation()
        line = asset.depreciation_line_ids.sorted('date')[0]
        line.action_post()
        self.assertEqual(line.move_id.journal_id,
                         asset.commission_move_id.journal_id)
        self.assertEqual(line.move_id.date, date(2025, 11, 30))
        balance = sum(self.env['account.move.line'].search([
            ('account_id', 'in', (self.acc_104 | self.acc_131).ids),
            ('parent_state', '=', 'posted'),
        ]).mapped('balance'))
        self.assertAlmostEqual(balance, asset.book_value, places=2)
