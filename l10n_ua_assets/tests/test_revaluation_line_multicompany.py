"""Рядки переоцінки ОЗ не видно користувачу іншої компанії (#685).

Документ переоцінки мав правило компанії, а модель рядків — ні:
користувач компанії Б знаходив, читав, змінював і видаляв рядки
переоцінки компанії А, а також додавав рядок у документ А.
"""

from datetime import date

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRevaluationLineMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        ua = cls.env.ref('base.ua').id
        cls.company_a = Company.create({'name': 'Компанія А (#685)', 'country_id': ua})
        cls.company_b = Company.create({'name': 'Компанія Б (#685)', 'country_id': ua})
        group = cls.env['l10n_ua.asset.group'].search([], limit=1) or \
            cls.env['l10n_ua.asset.group'].create({
                'code': '4', 'name': 'Машини та обладнання', 'min_useful_life': 5})
        groups = [cls.env.ref('base.group_user').id,
                  cls.env.ref('account.group_account_manager').id]

        def user(login, companies):
            return cls.env['res.users'].create({
                'name': login, 'login': login,
                'company_id': companies[0].id,
                'company_ids': [(6, 0, [c.id for c in companies])],
                'group_ids': [(6, 0, groups)],
            })
        cls.user_a = user('assets_685_a', [cls.company_a])
        cls.user_b = user('assets_685_b', [cls.company_b])
        cls.user_ab = user('assets_685_ab', [cls.company_a, cls.company_b])

        cls.asset_a = cls.env['l10n_ua.asset'].create({
            'name': 'Верстат (#685)',
            'acquisition_date': date(2025, 1, 15),
            'original_value': 100000,
            'group_id': group.id,
            'depreciation_method': 'straight_line',
            'useful_life': 60,
            'company_id': cls.company_a.id,
        })
        cls.reval_a = cls.env['l10n_ua.asset.revaluation'].create({
            'date': date(2025, 6, 30),
            'company_id': cls.company_a.id,
            'line_ids': [(0, 0, {
                'asset_id': cls.asset_a.id,
                'original_value_before': 100000,
                'accumulated_before': 0,
                'fair_value': 90000,
            })],
        })
        cls.line_a = cls.reval_a.line_ids
        cls.Line = cls.env['l10n_ua.asset.revaluation.line']

    def test_line_exists(self):
        """Передумова: у документа компанії А є рядок."""
        self.assertEqual(len(self.line_a), 1)

    def test_other_company_user_cannot_search_line(self):
        lines = self.Line.with_user(self.user_b).search([('id', '=', self.line_a.id)])
        self.assertFalse(lines)

    def test_other_company_user_cannot_read_line(self):
        with self.assertRaises(AccessError):
            self.line_a.with_user(self.user_b).read(['fair_value'])

    def test_other_company_user_cannot_write_line(self):
        with self.assertRaises(AccessError):
            self.line_a.with_user(self.user_b).write({'fair_value': 1})

    def test_other_company_user_cannot_unlink_line(self):
        with self.assertRaises(AccessError):
            self.line_a.with_user(self.user_b).unlink()

    def test_other_company_user_cannot_create_line_into_a(self):
        with self.assertRaises(AccessError):
            self.Line.with_user(self.user_b).create({
                'revaluation_id': self.reval_a.id,
                'asset_id': self.asset_a.id,
                'original_value_before': 100000,
                'accumulated_before': 0,
                'fair_value': 1,
            })

    def test_two_company_user_sees_only_selected(self):
        """Користувач А+Б бачить рядок А лише коли вибрана компанія А."""
        Line_ab = self.Line.with_user(self.user_ab)
        self.assertFalse(Line_ab.with_context(allowed_company_ids=self.company_b.ids)
                         .search([('id', '=', self.line_a.id)]))
        self.assertEqual(Line_ab.with_context(allowed_company_ids=self.company_a.ids)
                         .search([('id', '=', self.line_a.id)]), self.line_a)

    def test_same_company_user_sees_line(self):
        lines = self.Line.with_user(self.user_a).search([('id', '=', self.line_a.id)])
        self.assertEqual(lines, self.line_a)

    def test_rule_exists(self):
        rule = self.env.ref('l10n_ua_assets.l10n_ua_asset_revaluation_line_company_rule')
        self.assertTrue(rule['global'])
