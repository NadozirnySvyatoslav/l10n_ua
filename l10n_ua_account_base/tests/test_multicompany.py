"""Multi-company isolation for UA accounting documents — issue #178.

Without record rules the journal orders / OSV documents were visible across
ALL companies, including non-UA ones. These tests assert the global
multi-company rules scope each document to the user's allowed companies.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountBaseMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'ua_base_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('l10n_ua_account_base.group_ua_accountant').id])],
        })

    def _osv(self, company):
        return self.env['l10n_ua.osv'].create({
            'period_start': date(2026, 1, 1),
            'period_end': date(2026, 1, 31),
            'company_id': company.id,
        })

    def test_other_company_user_cannot_see_ua_osv(self):
        """A user of the non-UA company must not see the UA company's OSV."""
        osv = self._osv(self.company_ua)
        visible = self.env['l10n_ua.osv'].with_user(self.user_other).search([])
        self.assertNotIn(osv, visible)

    def test_same_company_user_sees_own_osv(self):
        """The rule still lets a user see their own company's OSV."""
        osv = self._osv(self.company_other)
        visible = self.env['l10n_ua.osv'].with_user(self.user_other).search([])
        self.assertIn(osv, visible)

    def test_rules_are_global(self):
        """Both multi-company accesses must exist and be restrictions."""
        for rule_id in (
            'l10n_ua_account_base.l10n_ua_journal_order_company_rule',
            'l10n_ua_account_base.l10n_ua_osv_company_rule',
        ):
            rule = self.env.ref(rule_id)
            self.assertEqual(rule.kind, 'restriction',
                             f'{rule_id} must be a restriction')
