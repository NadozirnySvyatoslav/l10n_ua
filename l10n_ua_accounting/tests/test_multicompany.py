"""Multi-company isolation for UA accounting documents — issue #178.

Without record rules these UA accounting models were visible across ALL
companies, including non-UA ones. These tests assert the global multi-company
rules scope each record to the user's allowed companies.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountingMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Customer', 'company_type': 'company'})
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'acc_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id])],
        })

    def _service_act(self, company):
        return self.env['l10n_ua.service.act'].create({
            'date': date(2026, 2, 10),
            'partner_id': self.partner.id,
            'company_id': company.id,
        })

    def test_other_company_user_cannot_see_ua_act(self):
        """A user of the non-UA company must not see the UA company's act."""
        act = self._service_act(self.company_ua)
        visible = self.env['l10n_ua.service.act'].with_user(self.user_other).search([])
        self.assertNotIn(act, visible)

    def test_same_company_user_sees_own_act(self):
        """The rule still lets a user see their own company's act."""
        act = self._service_act(self.company_other)
        visible = self.env['l10n_ua.service.act'].with_user(self.user_other).search([])
        self.assertIn(act, visible)

    def test_rules_are_global(self):
        """Each UA accounting model has a global multi-company ir.rule."""
        rule_xmlids = [
            'l10n_ua_accounting.l10n_ua_advance_report_company_rule',
            'l10n_ua_accounting.l10n_ua_period_closing_company_rule',
            'l10n_ua_accounting.l10n_ua_service_act_company_rule',
            'l10n_ua_accounting.l10n_ua_tax_period_company_rule',
            'l10n_ua_accounting.l10n_ua_aging_report_company_rule',
            'l10n_ua_accounting.l10n_ua_balance_report_company_rule',
            'l10n_ua_accounting.l10n_ua_pnl_report_company_rule',
            'l10n_ua_accounting.l10n_ua_cashflow_report_company_rule',
        ]
        for xmlid in rule_xmlids:
            rule = self.env.ref(xmlid)
            self.assertTrue(rule['global'], '%s must be global' % xmlid)
