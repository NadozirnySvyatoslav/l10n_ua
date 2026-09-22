"""Tests for КЕКВ/КФК/КПКВК/КВКВ classification models."""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_budget_base')
class TestKekv(TransactionCase):

    def test_seed_loaded(self):
        """Seed CSV should populate at least a basic КЕКВ tree."""
        Kekv = self.env['l10n_ua.kekv']
        self.assertTrue(Kekv.search_count([('code', '=', '2111')]))
        self.assertTrue(Kekv.search_count([('code', '=', '2273')]))  # Електроенергія

    def test_hierarchy(self):
        """Hierarchy should be navigable and full_name should be cumulative."""
        leaf = self.env.ref('l10n_ua_budget_base.kekv_2111')
        self.assertEqual(leaf.parent_id.code, '2110')
        self.assertEqual(leaf.parent_id.parent_id.code, '21')
        self.assertEqual(leaf.parent_id.parent_id.parent_id.code, '20')
        self.assertIn('Поточні видатки', leaf.full_name)
        self.assertIn('Заробітна плата', leaf.full_name)

    def test_unique_code_constraint(self):
        Kekv = self.env['l10n_ua.kekv']
        with self.assertRaises(Exception):
            Kekv.create({'code': '2111', 'name': 'Дублікат'})

    def test_expense_type_marker(self):
        """Top-level groups should be tagged with the right expense_type."""
        self.assertEqual(
            self.env.ref('l10n_ua_budget_base.kekv_20').expense_type, 'current')
        self.assertEqual(
            self.env.ref('l10n_ua_budget_base.kekv_30').expense_type, 'capital')
        self.assertEqual(
            self.env.ref('l10n_ua_budget_base.kekv_40').expense_type, 'lending')


@tagged('post_install', '-at_install', 'l10n_ua_budget_base')
class TestKfk(TransactionCase):

    def test_seed_loaded(self):
        Kfk = self.env['l10n_ua.kfk']
        self.assertTrue(Kfk.search_count([('code', '=', '0910')]))  # Дошкільна освіта
        self.assertTrue(Kfk.search_count([('code', '=', '0210')]))  # Військова оборона

    def test_division_compute(self):
        leaf = self.env.ref('l10n_ua_budget_base.kfk_0910')
        self.assertEqual(leaf.division, '09')

    def test_hierarchy(self):
        leaf = self.env.ref('l10n_ua_budget_base.kfk_0921')
        self.assertEqual(leaf.parent_id.code, '0920')
        self.assertEqual(leaf.parent_id.parent_id.code, '0900')


@tagged('post_install', '-at_install', 'l10n_ua_budget_base')
class TestKvkv(TransactionCase):

    def test_seed_loaded(self):
        Kvkv = self.env['l10n_ua.kvkv']
        mon = Kvkv.search([('code', '=', '220')], limit=1)
        self.assertTrue(mon)
        self.assertIn('освіти', mon.name.lower())

    def test_display_name(self):
        rec = self.env.ref('l10n_ua_budget_base.kvkv_220')
        self.assertIn('[220]', rec.display_name)


@tagged('post_install', '-at_install', 'l10n_ua_budget_base')
class TestKpkvk(TransactionCase):

    def test_seed_loaded(self):
        Kpkvk = self.env['l10n_ua.kpkvk']
        self.assertTrue(Kpkvk.search_count([('code', '=', '2201190')]))

    def test_code_format_constraint(self):
        Kpkvk = self.env['l10n_ua.kpkvk']
        with self.assertRaises(ValidationError):
            Kpkvk.create({'code': '12345', 'name': 'Short', 'year': 2025})
        # 7 characters on purpose: Odoo 20 no longer truncates a Char to its
        # `size`, so a longer value dies in Postgres before the constraint runs.
        with self.assertRaises(ValidationError):
            Kpkvk.create({'code': '1234abc', 'name': 'Bad', 'year': 2025})

    def test_kvkv_auto_link(self):
        """kvkv_code and kvkv_id should be derived from the leading 3 digits of code."""
        rec = self.env.ref('l10n_ua_budget_base.kpkvk_2201190_2025')
        self.assertEqual(rec.kvkv_code, '220')
        self.assertEqual(rec.kvkv_id.code, '220')

    def test_unique_per_year(self):
        Kpkvk = self.env['l10n_ua.kpkvk']
        rec = Kpkvk.create({'code': '2999999', 'name': 'Test', 'year': 2024})
        with self.assertRaises(Exception):
            Kpkvk.create({'code': '2999999', 'name': 'Dup', 'year': 2024})
        # Same code, different year — should be allowed
        Kpkvk.create({'code': '2999999', 'name': 'OK in next year', 'year': 2025})
        rec.unlink()
