"""Tests for fixed assets — from ACCOUNTING_UKRAINE.md TMC/OZ tasks.

Tests cover:
- Asset creation
- Depreciation methods (straight-line, declining balance, cumulative, production)
- Depreciation schedule generation
- State workflow (draft → open → paused → close)
- Commissioning and write-off acts
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAsset(TransactionCase):
    """Test fixed assets (основні засоби)."""

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

    def _create_asset(self, **kwargs):
        vals = {
            'name': 'Сервер HP ProLiant',
            'acquisition_date': date(2025, 1, 15),
            'original_value': 120000,
            'salvage_value': 10000,
            'group_id': self.asset_group.id,
            'depreciation_method': 'straight_line',
            'useful_life': 60,  # 5 years
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['l10n_ua.asset'].create(vals)

    def test_asset_creation(self):
        """Asset should be created in draft state."""
        asset = self._create_asset()
        self.assertEqual(asset.state, 'draft')
        self.assertTrue(asset.name)

    def test_asset_book_value(self):
        """Book value should be original - accumulated depreciation."""
        asset = self._create_asset()
        self.assertEqual(asset.book_value, 120000)  # No depreciation yet

    def test_asset_commissioning(self):
        """Commissioning should set state to open."""
        asset = self._create_asset()
        asset.action_commission()
        self.assertEqual(asset.state, 'open')
        self.assertTrue(asset.commission_date)
        self.assertTrue(asset.commission_act_number)

    def test_straight_line_depreciation(self):
        """Straight-line: (original - salvage) / useful_life months."""
        asset = self._create_asset()
        # Monthly: (120000 - 10000) / 60 = 1833.33
        expected = (120000 - 10000) / 60
        self.assertAlmostEqual(asset.depreciation_amount, expected, places=2)

    def test_depreciation_schedule_generation(self):
        """Computing depreciation should generate schedule lines."""
        asset = self._create_asset()
        asset.action_commission()
        asset.action_compute_depreciation()
        self.assertTrue(asset.depreciation_line_ids,
                        'Depreciation schedule should have lines')
        self.assertEqual(len(asset.depreciation_line_ids), 60)

    def test_declining_balance_depreciation(self):
        """Declining balance should use accelerated rate on depreciable base."""
        asset = self._create_asset(
            depreciation_method='declining_balance',
            annual_depreciation_rate=40.0,
        )
        # First month: (120000 - 10000) × 40% / 12 = 3666.67
        depreciable = 120000 - 10000  # original - salvage
        expected_first = depreciable * 40 / 100 / 12
        self.assertAlmostEqual(asset.depreciation_amount, expected_first, places=2)

    def test_asset_pause_resume(self):
        """Should be able to pause and resume depreciation."""
        asset = self._create_asset()
        asset.action_commission()
        self.assertEqual(asset.state, 'open')
        asset.action_pause()
        self.assertEqual(asset.state, 'paused')
        asset.action_resume()
        self.assertEqual(asset.state, 'open')

    def test_asset_write_off(self):
        """Write-off should close the asset."""
        asset = self._create_asset()
        asset.action_commission()
        asset.action_write_off()
        self.assertEqual(asset.state, 'close')
        self.assertTrue(asset.writeoff_date)
        self.assertTrue(asset.writeoff_act_number)

    def test_asset_group_reference_data(self):
        """Asset groups should have required fields."""
        self.assertTrue(self.asset_group.code)
        self.assertTrue(self.asset_group.name)
        self.assertGreaterEqual(self.asset_group.min_useful_life, 0)

    # --- #625: П(С)БО 7 п.29 — амортизація з наступного місяця ---

    def test_depreciation_starts_month_after_commissioning(self):
        """Введено 31.10 → перший рядок у листопаді, на кінець місяця."""
        asset = self._create_asset(commission_date=date(2025, 10, 31),
                                   acquisition_date=date(2025, 10, 20))
        asset.action_commission()
        self.assertEqual(asset.commission_date, date(2025, 10, 31))
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted('date')
        self.assertEqual(len(lines), 60)
        self.assertEqual(lines[0].date, date(2025, 11, 30))
        self.assertEqual(lines[1].date, date(2025, 12, 31))
        self.assertEqual(lines[3].date, date(2026, 2, 28))
        self.assertEqual(lines[-1].date, date(2030, 10, 31))
        # Жодного рядка в місяці введення.
        self.assertFalse(lines.filtered(
            lambda l: (l.date.year, l.date.month) == (2025, 10)))

    def test_depreciation_start_first_day_of_month(self):
        """Введено 01.03 → перший рядок у квітні, а не в березні."""
        asset = self._create_asset(commission_date=date(2025, 3, 1))
        asset.action_compute_depreciation()
        first = asset.depreciation_line_ids.sorted('date')[0]
        self.assertEqual(first.date, date(2025, 4, 30))

    def test_cumulative_depreciation_dates_and_total(self):
        """Кумулятивний метод: ті самі дати, повна сума амортизації."""
        asset = self._create_asset(commission_date=date(2025, 1, 15),
                                   depreciation_method='cumulative',
                                   useful_life=36)
        asset.action_compute_depreciation()
        lines = asset.depreciation_line_ids.sorted('date')
        self.assertEqual(lines[0].date, date(2025, 2, 28))
        # Перший рік — найбільша сума: 110000 × 3/6 / 12.
        self.assertAlmostEqual(lines[0].amount, round(110000 * 3 / 6 / 12, 2),
                               places=2)
        self.assertAlmostEqual(sum(lines.mapped('amount')), 110000, delta=1.0)
        self.assertLessEqual(lines[-1].date, date(2028, 1, 31))

    def test_recompute_continues_after_posted_lines(self):
        """Існуючий графік (старі рядки з місяця введення) продовжується
        без розриву після останнього проведеного рядка."""
        asset = self._create_asset(commission_date=date(2025, 1, 15),
                                   useful_life=12, salvage_value=0,
                                   original_value=12000)
        Dep = self.env['l10n_ua.asset.depreciation']
        for i in range(2):
            Dep.create({
                'asset_id': asset.id,
                'date': date(2025, 1 + i, 28),
                'amount': 1000,
                'accumulated': 1000 * (i + 1),
                'remaining': 12000 - 1000 * (i + 1),
                'state': 'posted',
            })
        asset.action_compute_depreciation()
        drafts = asset.depreciation_line_ids.filtered(
            lambda l: l.state == 'draft').sorted('date')
        self.assertEqual(len(drafts), 10)
        self.assertEqual(drafts[0].date, date(2025, 3, 31))
        self.assertEqual(drafts[-1].date, date(2025, 12, 31))
