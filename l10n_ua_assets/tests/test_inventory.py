"""Тести інвентаризації ОЗ — Наказ Мінфіну №879, Інв-1, Інв-3."""

from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestAssetInventory(TransactionCase):
    """Тести інвентаризації ОЗ."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Унікальна тестова група — щоб дії з фільтром не бачили
        # demo/прод-активи в БД
        cls.asset_group = cls.env['l10n_ua.asset.group'].create({
            'code': 'TEST-INV',
            'name': 'Test inventory group',
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

        cls.acc_asset = _get_or_create('1001', 'ОЗ', 'asset_fixed')
        cls.acc_accum = _get_or_create('1311', 'Знос ОЗ', 'asset_fixed')
        cls.acc_shortage = _get_or_create('9471', 'Нестачі', 'expense')
        cls.acc_surplus = _get_or_create('7461', 'Лишки/інші доходи', 'income_other')

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
        asset = self.env['l10n_ua.asset'].create(vals)
        asset.action_commission()
        return asset

    def _post_depreciation(self, asset, amount):
        return self.env['l10n_ua.asset.depreciation'].create({
            'asset_id': asset.id,
            'date': date(2025, 2, 28),
            'amount': amount,
            'accumulated': amount,
            'remaining': asset.original_value - amount,
            'state': 'posted',
        })

    def _common_vals(self):
        return {
            'date': date(2025, 6, 30),
            'order_number': 'Наказ №1',
            'order_date': date(2025, 6, 25),
            # Завжди фільтруємо по тестовій групі, щоб не вловлювати
            # demo/прод-активи в спільній БД
            'filter_group_id': self.asset_group.id,
            'journal_id': self.journal.id,
            'fixed_asset_account_id': self.acc_asset.id,
            'accumulated_depreciation_account_id': self.acc_accum.id,
            'shortage_expense_account_id': self.acc_shortage.id,
            'surplus_income_account_id': self.acc_surplus.id,
        }

    def test_creation_sequence(self):
        """Sequence ІНВ-..."""
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        self.assertTrue(inv.name.startswith('ІНВ-'))
        self.assertEqual(inv.state, 'draft')

    def test_fill_lines_no_filter(self):
        """Заповнення рядків бере всіх відкритих ОЗ."""
        a1 = self._create_asset(name='Asset 1')
        a2 = self._create_asset(name='Asset 2')
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        self.assertEqual(inv.state, 'in_progress')
        self.assertEqual(len(inv.line_ids), 2)
        self.assertEqual(set(inv.line_ids.mapped('asset_id.id')), {a1.id, a2.id})

    def test_fill_lines_with_group_filter(self):
        """Фільтр по групі обмежує."""
        other_group = self.env['l10n_ua.asset.group'].create({
            'code': '99', 'name': 'Other'})
        a1 = self._create_asset(name='Asset 1')
        a2 = self._create_asset(name='Asset 2', group_id=other_group.id)
        inv = self.env['l10n_ua.asset.inventory'].create({
            **self._common_vals(),
            'filter_group_id': self.asset_group.id,
        })
        inv.action_fill_lines()
        self.assertEqual(len(inv.line_ids), 1)
        self.assertEqual(inv.line_ids.asset_id, a1)

    def test_fill_lines_excludes_already_added(self):
        """Повторне заповнення не дублює."""
        a1 = self._create_asset(name='Asset 1')
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        self.assertEqual(len(inv.line_ids), 1)
        # Додаємо ще ОЗ і знов заповнюємо
        a2 = self._create_asset(name='Asset 2')
        inv.action_fill_lines()
        self.assertEqual(len(inv.line_ids), 2)

    def test_discrepancy_match(self):
        """found=True → discrepancy='match'."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        inv.line_ids[0].found = True
        self.assertEqual(inv.line_ids[0].discrepancy, 'match')

    def test_discrepancy_shortage(self):
        """not found → shortage."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        self.assertEqual(inv.line_ids[0].discrepancy, 'shortage')

    def test_add_surplus(self):
        """Додавання рядка-лишку."""
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_add_surplus()
        self.assertEqual(inv.state, 'in_progress')
        surplus = inv.line_ids.filtered(lambda l: l.is_surplus)
        self.assertEqual(len(surplus), 1)
        self.assertEqual(surplus.discrepancy, 'surplus')

    def test_done_no_changes(self):
        """Завершити без розбіжностей — без проводки."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        inv.line_ids[0].found = True
        inv.action_done()
        self.assertEqual(inv.state, 'done')
        self.assertFalse(inv.move_id)

    def test_done_shortage_creates_move_and_writeoff(self):
        """Нестача → write-off активу + проводка Дт 947 / Кт 10 + Дт 131 / Кт 10."""
        a1 = self._create_asset(original_value=100000)
        self._post_depreciation(a1, 20000)
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        # Залишаємо found=False — нестача
        inv.action_done()
        self.assertEqual(inv.state, 'done')
        # Актив списано
        self.assertEqual(a1.state, 'close')
        self.assertTrue(a1.writeoff_date)
        # Проводка
        self.assertTrue(inv.move_id)
        self.assertEqual(inv.move_id.state, 'posted')
        # Дт 947 на book_value (80000)
        shortage_lines = inv.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_shortage)
        self.assertAlmostEqual(sum(shortage_lines.mapped('debit')), 80000, places=2)
        # Дт 131 на знос (20000)
        accum_lines = inv.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_accum)
        self.assertAlmostEqual(sum(accum_lines.mapped('debit')), 20000, places=2)
        # Кт 10 на 100000 (original)
        asset_credits = inv.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_asset)
        self.assertAlmostEqual(sum(asset_credits.mapped('credit')), 100000, places=2)
        # Баланс
        d = sum(inv.move_id.line_ids.mapped('debit'))
        c = sum(inv.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(d, c, places=2)

    def test_done_surplus_creates_asset_and_move(self):
        """Лишок → новий ОЗ + проводка Дт 10 / Кт 746."""
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_add_surplus()
        inv.line_ids.write({
            'surplus_name': 'Знайдений принтер',
            'surplus_value': 5000,
        })
        inv.action_done()
        self.assertEqual(inv.state, 'done')
        line = inv.line_ids[0]
        self.assertTrue(line.created_asset_id)
        self.assertEqual(line.created_asset_id.state, 'open')
        self.assertAlmostEqual(line.created_asset_id.original_value, 5000, places=2)
        # Проводка
        self.assertTrue(inv.move_id)
        asset_debits = inv.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_asset)
        self.assertAlmostEqual(sum(asset_debits.mapped('debit')), 5000, places=2)
        surplus_credits = inv.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_surplus)
        self.assertAlmostEqual(sum(surplus_credits.mapped('credit')), 5000, places=2)

    def test_done_requires_accounts(self):
        """Не можна завершити з нестачею без рахунків."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({
            'date': date(2025, 6, 30),
        })
        inv.action_fill_lines()
        with self.assertRaises(UserError):
            inv.action_done()

    def test_done_only_from_in_progress(self):
        """Не можна завершити з draft."""
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        with self.assertRaises(UserError):
            inv.action_done()

    def test_cannot_cancel_done(self):
        """Не можна скасувати завершену."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        inv.line_ids[0].found = True
        inv.action_done()
        with self.assertRaises(UserError):
            inv.action_cancel()

    def test_summary_computed(self):
        """Підсумок: matched/shortage/surplus counts."""
        a1 = self._create_asset(name='A1', original_value=10000)
        a2 = self._create_asset(name='A2', original_value=20000)
        a3 = self._create_asset(name='A3', original_value=30000)
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        inv.line_ids.filtered(lambda l: l.asset_id == a1).found = True
        # A2 та A3 залишаються як shortage
        inv.action_add_surplus()
        inv.line_ids.filtered('is_surplus').write({
            'surplus_name': 'X', 'surplus_value': 1000,
        })
        # Force recompute
        inv.invalidate_recordset(['line_count', 'matched_count',
                                  'shortage_count', 'surplus_count',
                                  'shortage_amount', 'surplus_amount'])
        self.assertEqual(inv.line_count, 4)
        self.assertEqual(inv.matched_count, 1)
        self.assertEqual(inv.shortage_count, 2)
        self.assertEqual(inv.surplus_count, 1)
        self.assertAlmostEqual(inv.shortage_amount, 50000, places=2)
        self.assertAlmostEqual(inv.surplus_amount, 1000, places=2)

    def test_cannot_delete_done(self):
        """Не можна видалити завершену."""
        a1 = self._create_asset()
        inv = self.env['l10n_ua.asset.inventory'].create({**self._common_vals()})
        inv.action_fill_lines()
        inv.line_ids[0].found = True
        inv.action_done()
        with self.assertRaises(UserError):
            inv.unlink()
