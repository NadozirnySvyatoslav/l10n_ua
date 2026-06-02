"""Тести переоцінки ОЗ — П(С)БО 7, п. 16-21."""

from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install')
class TestAssetRevaluation(TransactionCase):
    """Тести переоцінки основних засобів."""

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
        # Журнал
        cls.journal = cls.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'Тестовий загальний',
                'code': 'TGEN',
                'type': 'general',
                'company_id': cls.company.id,
            })

        # Створимо чотири рахунки (10, 131, 411, 975)
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
        cls.acc_accum = _get_or_create('1311', 'Знос ОЗ', 'asset_fixed')
        cls.acc_surplus = _get_or_create('4111', 'Дооцінка', 'equity')
        cls.acc_impair = _get_or_create('9751', 'Уцінка', 'expense')
        cls.acc_other_income = _get_or_create('7461', 'Інші доходи', 'income_other')

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
        """Записати один проведений рядок амортизації."""
        return self.env['l10n_ua.asset.depreciation'].create({
            'asset_id': asset.id,
            'date': date_ or date(2025, 2, 28),
            'amount': amount,
            'accumulated': amount,
            'remaining': asset.original_value - amount,
            'state': 'posted',
            'line_type': 'depreciation',
        })

    def _common_revaluation_vals(self):
        return {
            'date': date(2025, 6, 30),
            'journal_id': self.journal.id,
            'fixed_asset_account_id': self.acc_asset.id,
            'accumulated_depreciation_account_id': self.acc_accum.id,
            'revaluation_surplus_account_id': self.acc_surplus.id,
            'impairment_loss_account_id': self.acc_impair.id,
            'other_income_account_id': self.acc_other_income.id,
        }

    def test_revaluation_index_computation(self):
        """Індекс = fair_value / book_value_before."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        # book_value = 100000 - 20000 = 80000
        # fair_value = 100000 → index = 1.25
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        line = revaluation.line_ids
        self.assertAlmostEqual(line.book_value_before, 80000, places=2)
        self.assertAlmostEqual(line.revaluation_index, 1.25, places=4)
        self.assertAlmostEqual(line.original_value_after, 125000, places=2)
        self.assertAlmostEqual(line.accumulated_after, 25000, places=2)
        self.assertAlmostEqual(line.book_value_after, 100000, places=2)
        self.assertEqual(line.revaluation_type, 'increase')

    def test_revaluation_decrease(self):
        """Уцінка: fair_value < book_value_before."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        # book=80000, fair=60000 → index=0.75
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 60000,
            })],
        })
        line = revaluation.line_ids
        self.assertAlmostEqual(line.revaluation_index, 0.75, places=4)
        self.assertAlmostEqual(line.original_value_after, 75000, places=2)
        self.assertAlmostEqual(line.accumulated_after, 15000, places=2)
        self.assertAlmostEqual(line.book_value_after, 60000, places=2)
        self.assertEqual(line.revaluation_type, 'decrease')
        self.assertLess(line.revaluation_amount, 0)

    def test_revaluation_confirm_updates_asset(self):
        """Підтвердження повинно змінити original_value та accumulated."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        self.assertAlmostEqual(asset.accumulated_depreciation, 20000, places=2)

        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        revaluation.action_confirm()

        # Після дооцінки: original=125000, accumulated=25000
        self.assertEqual(revaluation.state, 'confirmed')
        self.assertAlmostEqual(asset.original_value, 125000, places=2)
        self.assertAlmostEqual(asset.accumulated_depreciation, 25000, places=2)
        self.assertAlmostEqual(asset.book_value, 100000, places=2)

    def test_revaluation_creates_move(self):
        """Дооцінка створює бухгалтерську проводку з потрібними рахунками."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        revaluation.action_confirm()
        self.assertTrue(revaluation.move_id, 'Проводка повинна бути створена')
        self.assertEqual(revaluation.move_id.state, 'posted')
        # 3 рядки: Дт 10 (25000), Кт 131 (5000), Кт 411 (20000)
        self.assertEqual(len(revaluation.move_id.line_ids), 3)
        debit_total = sum(revaluation.move_id.line_ids.mapped('debit'))
        credit_total = sum(revaluation.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(debit_total, credit_total, places=2)
        # Дт 10 на 25000 (ΔOriginal)
        asset_lines = revaluation.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_asset)
        self.assertAlmostEqual(sum(asset_lines.mapped('debit')), 25000, places=2)
        self.assertAlmostEqual(sum(asset_lines.mapped('credit')), 0, places=2)
        # Кт 411 на 20000 (net Δbook = fair - book_before = 100000 - 80000)
        surplus_lines = revaluation.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_surplus)
        self.assertAlmostEqual(sum(surplus_lines.mapped('credit')), 20000, places=2)

    def test_revaluation_cancel_reverts(self):
        """Скасування повертає original_value та accumulated."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        revaluation.action_confirm()
        # Перевірка
        self.assertAlmostEqual(asset.original_value, 125000, places=2)
        # Скасування
        revaluation.action_cancel()
        self.assertEqual(revaluation.state, 'cancelled')
        self.assertAlmostEqual(asset.original_value, 100000, places=2)
        self.assertAlmostEqual(asset.accumulated_depreciation, 20000, places=2)

    def test_revaluation_requires_accounts_for_confirm(self):
        """Не можна підтвердити без рахунків."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            'date': date(2025, 6, 30),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        with self.assertRaises(UserError):
            revaluation.action_confirm()

    def test_negative_fair_value_rejected(self):
        """Від'ємна справедлива вартість не приймається."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        with self.assertRaises(ValidationError):
            self.env['l10n_ua.asset.revaluation'].create({
                **self._common_revaluation_vals(),
                'line_ids': [(0, 0, {
                    'asset_id': asset.id,
                    'original_value_before': asset.original_value,
                    'accumulated_before': asset.accumulated_depreciation,
                    'fair_value': -100,
                })],
            })

    def test_revaluation_sequence(self):
        """Створення повинно присвоїти послідовний номер."""
        asset = self._create_asset()
        asset.action_commission()
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': asset.book_value or 1,
            })],
        })
        self.assertNotEqual(revaluation.name, 'Нова')
        self.assertTrue(revaluation.name.startswith('ПО-'))

    def test_revaluation_offset_dooсinka_after_uсinka(self):
        """П(С)БО 7 п.20: дооцінка після уцінки → Кт 746, надлишок → Кт 411."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        # Перша операція: уцінка book 80000 → 60000 (Δbook=-20000)
        rev1 = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 60000,
            })],
        })
        rev1.action_confirm()
        self.assertAlmostEqual(asset.cumulative_revaluation_balance, -20000, places=2)
        # Друга операція: дооцінка book 60000 → 70000 (Δbook=+10000, прибл.)
        # У межах |prior|=20000 — повністю в 746
        rev2 = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'date': date(2025, 9, 30),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 70000,
            })],
        })
        rev2.action_confirm()
        # Δbook = 10000, все в 746 (бо |prior|=20000 покриває)
        income_lines = rev2.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_other_income)
        surplus_lines = rev2.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_surplus)
        self.assertAlmostEqual(sum(income_lines.mapped('credit')), 10000, places=2)
        self.assertAlmostEqual(sum(surplus_lines.mapped('credit')), 0, places=2)

    def test_revaluation_offset_uсinka_after_dooсinka(self):
        """П(С)БО 7 п.21: уцінка після дооцінки → Дт 411, надлишок → Дт 975."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        # Дооцінка book 80000 → 100000 (Δbook=+20000)
        rev1 = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        rev1.action_confirm()
        self.assertAlmostEqual(asset.cumulative_revaluation_balance, 20000, places=2)
        # Уцінка book 100000 → 70000 (Δbook=-30000)
        # У межах prior=20000 — Дт 411 на 20000, решта (10000) → Дт 975
        rev2 = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'date': date(2025, 9, 30),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 70000,
            })],
        })
        rev2.action_confirm()
        surplus_lines = rev2.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_surplus)
        impair_lines = rev2.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_impair)
        self.assertAlmostEqual(sum(surplus_lines.mapped('debit')), 20000, places=2)
        self.assertAlmostEqual(sum(impair_lines.mapped('debit')), 10000, places=2)

    def test_revaluation_cancel_blocked_by_later_depreciation(self):
        """Не можна скасувати переоцінку якщо після неї проведена амортизація."""
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        revaluation.action_confirm()
        # Провести амортизацію ПІСЛЯ переоцінки
        self._post_depreciation(asset, 2000, date_=date(2025, 7, 31))
        with self.assertRaises(UserError):
            revaluation.action_cancel()

    def test_asset_action_draft_blocked_by_confirmed_revaluation(self):
        """action_draft на ОЗ блокується якщо є підтверджені переоцінки."""
        asset = self._create_asset()
        asset.action_commission()
        self._post_depreciation(asset, 10000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': asset.book_value + 5000,
            })],
        })
        revaluation.action_confirm()
        with self.assertRaises(UserError):
            asset.action_draft()

    def test_depreciation_line_revaluation_protected(self):
        """Коригувальний рядок переоцінки не можна видалити."""
        asset = self._create_asset()
        asset.action_commission()
        self._post_depreciation(asset, 10000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': asset.book_value + 5000,
            })],
        })
        revaluation.action_confirm()
        adj = self.env['l10n_ua.asset.depreciation'].search([
            ('asset_id', '=', asset.id),
            ('line_type', '=', 'revaluation'),
        ])
        self.assertTrue(adj)
        with self.assertRaises(UserError):
            adj.unlink()

    def test_compute_depreciation_after_revaluation(self):
        """Після переоцінки графік амортизації базується на поточному residual."""
        asset = self._create_asset(original_value=100000, salvage_value=0,
                                   useful_life=10, depreciation_method='straight_line')
        asset.action_commission()
        # 4 місяці амортизації по 10000
        for i in range(4):
            self.env['l10n_ua.asset.depreciation'].create({
                'asset_id': asset.id,
                'date': date(2025, 2 + i, 28),
                'amount': 10000,
                'accumulated': 10000 * (i + 1),
                'remaining': 100000 - 10000 * (i + 1),
                'state': 'posted',
                'line_type': 'depreciation',
            })
        # accumulated = 40000, book = 60000
        # Дооцінка до book = 90000 (Δbook=+30000)
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 90000,
            })],
        })
        revaluation.action_confirm()
        # Тепер book ≈ 90000, посаджено 4 місяці, лишилось 6
        # Майбутній місяць = 90000/6 = 15000
        asset.action_compute_depreciation()
        future = asset.depreciation_line_ids.filtered(
            lambda l: l.state == 'draft' and l.line_type == 'depreciation')
        self.assertEqual(len(future), 6)
        for line in future:
            self.assertAlmostEqual(line.amount, 15000, places=2)

    def test_action_create_revaluation_from_asset(self):
        """Кнопка з ОЗ створює чернетку переоцінки."""
        asset = self._create_asset()
        asset.action_commission()
        result = asset.action_create_revaluation()
        self.assertEqual(result['res_model'], 'l10n_ua.asset.revaluation')
        rev = self.env['l10n_ua.asset.revaluation'].browse(result['res_id'])
        self.assertEqual(rev.state, 'draft')
        self.assertEqual(len(rev.line_ids), 1)
        self.assertEqual(rev.line_ids.asset_id, asset)

    def test_confirm_refreshes_stale_snapshot(self):
        """#101: якщо депреціація постилась між draft і confirm —
        snapshot оновлюється з live значень асета.
        """
        asset = self._create_asset(original_value=100000)
        asset.action_commission()
        self._post_depreciation(asset, 20000)
        # Створюємо draft зі snapshot accumulated=20000
        rev = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': 100000,
            })],
        })
        # Між створенням і confirm — пройшла ще одна амортизація
        self._post_depreciation(asset, 5000, date_=date(2025, 5, 31))
        # asset.accumulated_depreciation тепер 25000
        self.assertAlmostEqual(asset.accumulated_depreciation, 25000, places=2)
        # Підтверджуємо — snapshot має оновитися
        rev.action_confirm()
        line = rev.line_ids
        self.assertAlmostEqual(line.accumulated_before, 25000, places=2)
        # book_value_before = 100000 - 25000 = 75000
        # index = 100000 / 75000 = 1.333...
        # new_original = 100000 * 1.333... = 133333.33
        # new_accumulated = 25000 * 1.333... = 33333.33
        self.assertAlmostEqual(asset.original_value, 133333.33, places=2)
        self.assertAlmostEqual(asset.book_value, 100000, places=0)

    def test_confirm_rejects_written_off_asset(self):
        """#110: action_confirm перевіряє стан асета."""
        asset = self._create_asset()
        asset.action_commission()
        self._post_depreciation(asset, 10000)
        rev = self.env['l10n_ua.asset.revaluation'].create({
            **self._common_revaluation_vals(),
            'line_ids': [(0, 0, {
                'asset_id': asset.id,
                'original_value_before': asset.original_value,
                'accumulated_before': asset.accumulated_depreciation,
                'fair_value': asset.book_value + 1000,
            })],
        })
        # Списати асет
        asset.action_write_off()
        # Тепер confirm має впасти
        with self.assertRaises(UserError):
            rev.action_confirm()
