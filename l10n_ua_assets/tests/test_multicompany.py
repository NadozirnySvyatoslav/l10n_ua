"""Multi-company isolation for UA fixed-asset documents — issue #178.

Without record rules the asset documents were visible across ALL companies,
including non-UA ones. These tests assert the global multi-company rules scope
each document to the user's allowed companies.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAssetsMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.asset_group = cls.env['l10n_ua.asset.group'].search([], limit=1)
        if not cls.asset_group:
            cls.asset_group = cls.env['l10n_ua.asset.group'].create({
                'code': '4',
                'name': 'Машини та обладнання',
                'min_useful_life': 5,
            })
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'assets_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id])],
        })

    def _asset(self, company):
        return self.env['l10n_ua.asset'].create({
            'name': 'Сервер HP ProLiant',
            'acquisition_date': date(2025, 1, 15),
            'original_value': 120000,
            'salvage_value': 10000,
            'group_id': self.asset_group.id,
            'depreciation_method': 'straight_line',
            'useful_life': 60,
            'company_id': company.id,
        })

    def test_rules_exist_and_global(self):
        """All five UA asset models must have a global multi-company rule."""
        for xmlid in (
            'l10n_ua_assets.l10n_ua_asset_company_rule',
            'l10n_ua_assets.l10n_ua_asset_inventory_company_rule',
            'l10n_ua_assets.l10n_ua_asset_modernization_company_rule',
            'l10n_ua_assets.l10n_ua_asset_revaluation_company_rule',
            'l10n_ua_assets.l10n_ua_mnma_company_rule',
        ):
            rule = self.env.ref(xmlid)
            self.assertEqual(
                rule.kind, 'restriction',
                "%s must be a restriction" % xmlid)

    def test_other_company_user_cannot_see_ua_asset(self):
        """A user of the non-UA company must not see the UA company's asset."""
        asset = self._asset(self.company_ua)
        visible = self.env['l10n_ua.asset'].with_user(self.user_other).search([])
        self.assertNotIn(asset, visible)

    def test_same_company_user_sees_own_asset(self):
        """The rule still lets a user see their own company's asset."""
        asset = self._asset(self.company_other)
        visible = self.env['l10n_ua.asset'].with_user(self.user_other).search([])
        self.assertIn(asset, visible)
