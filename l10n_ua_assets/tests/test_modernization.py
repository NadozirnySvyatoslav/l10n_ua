"""Тести модернізації ОЗ — П(С)БО 7 п.14."""

from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install')
class TestAssetModernization(TransactionCase):
    """Тести модернізації основних засобів."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.asset_group = cls.env['l10n_ua.asset.group'].search([], limit=1)
        if not cls.asset_group:
            cls.asset_group = cls.env['l10n_ua.asset.group'].create({
                'code': '4',
                'name': 'Машини та обладнання',
                'min_useful_life': 5,
            })
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1) or cls.env['account.journal'].create({
            'name': 'Тестовий загальний',
            'code': 'TGEN',
            'type': 'general',
            'company_id': cls.company.id,
        })

        Account = cls.env['account.account']

        def _get_or_create(code, name, account_type):
            acc = Account.search([
                ('code', '=', code),
                ('company_ids', 'in', cls.company.id),
            ], limit=1)
            if not acc:
                acc = Account.create({
                    'code': code,
                    'name': name,
                    'account_type': account_type,
                    'company_ids': [(4, cls.company.id)],
                })
            return acc

        cls.acc_asset = _get_or_create('1001', 'ОЗ', 'asset_fixed')
        cls.acc_source = _get_or_create('1521', 'Кап. інвестиції', 'asset_non_current')

    def _create_asset(self, **kwargs):
        vals = {
            'name': 'Тестовий ОЗ',
            'acquisition_date': date(2025, 1, 15),
            'original_value': 100000,
            'salvage_value': 0,
            'group_id': self.asset_group.id,
            'depreciation_method': 'straight_line',
            'useful_life': 60,
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['l10n_ua.asset'].create(vals)

    def _post_depreciation(self, asset, amount, date_=None):
        return self.env['l10n_ua.asset.depreciation'].create({
            'asset_id': asset.id,
            'date': date_ or date(2025, 2, 28),
            'amount': amount,
            'accumulated': amount,
            'remaining': asset.original_value - amount,
            'state': 'posted',
        })

    def _common_vals(self):
        return {
            'date': date(2025, 6, 30),
            'document_reference': 'Договір №42 від 25.06.2025',
            'journal_id': self.journal.id,
            'fixed_asset_account_id': self.acc_asset.id,
            'source_account_id': self.acc_source.id,
        }

    def test_creation_sequence(self):
        """Створення — sequence МД-..."""
        asset = self._create_asset()
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 10000,
            })],
        })
        self.assertTrue(mod.name.startswith('МД-'))
        self.assertEqual(mod.state, 'draft')

    def test_after_values(self):
        """Computed after values."""
        asset = self._create_asset(original_value=100000, useful_life=60)
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 15000,
                'useful_life_extension': 12,
            })],
        })
        line = mod.line_ids
        self.assertAlmostEqual(line.original_value_after, 115000, places=2)
        self.assertEqual(line.useful_life_after, 72)

    def test_confirm_updates_asset(self):
        """Підтвердження збільшує original_value і useful_life."""
        asset = self._create_asset(original_value=100000, useful_life=60)
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 20000,
                'useful_life_extension': 6,
            })],
        })
        mod.action_confirm()
        self.assertEqual(mod.state, 'confirmed')
        self.assertAlmostEqual(asset.original_value, 120000, places=2)
        self.assertEqual(asset.useful_life, 66)

    def test_confirm_creates_move(self):
        """Проводка Дт 10 / Кт 152."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 25000,
            })],
        })
        mod.action_confirm()
        self.assertTrue(mod.move_id)
        self.assertEqual(mod.move_id.state, 'posted')
        # Дт 10 на 25000
        asset_lines = mod.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_asset)
        self.assertAlmostEqual(sum(asset_lines.mapped('debit')), 25000, places=2)
        # Кт 152 на 25000
        source_lines = mod.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_source)
        self.assertAlmostEqual(sum(source_lines.mapped('credit')), 25000, places=2)
        # Баланс
        debit_total = sum(mod.move_id.line_ids.mapped('debit'))
        credit_total = sum(mod.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(debit_total, credit_total, places=2)

    def test_cancel_reverts(self):
        """Скасування повертає original_value і useful_life."""
        asset = self._create_asset(original_value=100000, useful_life=60)
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 25000,
                'useful_life_extension': 12,
            })],
        })
        mod.action_confirm()
        self.assertEqual(asset.useful_life, 72)
        mod.action_cancel()
        self.assertEqual(mod.state, 'cancelled')
        self.assertAlmostEqual(asset.original_value, 100000, places=2)
        self.assertEqual(asset.useful_life, 60)

    def test_cancel_blocked_by_later_depreciation(self):
        """Не можна скасувати якщо після модернізації провели амортизацію."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 20000,
            })],
        })
        mod.action_confirm()
        # Провести амортизацію після модернізації
        self._post_depreciation(asset, 2000, date_=date(2025, 7, 31))
        with self.assertRaises(UserError):
            mod.action_cancel()

    def test_confirm_requires_amount(self):
        """Не можна підтвердити з нульовою сумою."""
        asset = self._create_asset()
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 0,
            })],
        })
        with self.assertRaises(UserError):
            mod.action_confirm()

    def test_negative_amount_rejected(self):
        """Від'ємна сума не приймається в confirmed state."""
        asset = self._create_asset()
        asset.action_commission()
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 5000,
            })],
        })
        mod.action_confirm()
        # У confirmed стані constraint спрацьовує
        with self.assertRaises(ValidationError):
            mod.line_ids.write({'amount': -100})

    def test_negative_useful_life_extension_rejected(self):
        """Від'ємне подовження строку не приймається."""
        asset = self._create_asset()
        asset.action_commission()
        with self.assertRaises(ValidationError):
            self.env['l10n_ua.asset.modernization'].create({
                **self._common_vals(),
                'line_ids': [(0, 0, {
                    'asset_id': asset.id,
                    'original_value_before': asset.original_value,
                    'useful_life_before': asset.useful_life,
                    'amount': 10000,
                    'useful_life_extension': -5,
                })],
            })

    def test_action_create_from_asset(self):
        """Кнопка «Модернізувати» створює чернетку."""
        asset = self._create_asset()
        asset.action_commission()
        result = asset.action_create_modernization()
        self.assertEqual(result['res_model'], 'l10n_ua.asset.modernization')
        mod = self.env['l10n_ua.asset.modernization'].browse(result['res_id'])
        self.assertEqual(mod.state, 'draft')
        self.assertEqual(len(mod.line_ids), 1)
        self.assertEqual(mod.line_ids.asset_id, asset)

    def test_modernization_count(self):
        """Smart-button лічильник."""
        asset = self._create_asset()
        asset.action_commission()
        self.assertEqual(asset.modernization_count, 0)
        mod = self.env['l10n_ua.asset.modernization'].create({
            **self._common_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'useful_life_before': asset.useful_life,
                'amount': 10000,
            })],
        })
        mod.action_confirm()
        asset.invalidate_recordset(['modernization_count'])
        self.assertEqual(asset.modernization_count, 1)
