"""Multi-company isolation for FOP documents — issue #178.

Without record rules the FOP documents were visible across ALL companies,
including non-UA ones. These tests assert the global multi-company rules scope
each document to the user's allowed companies.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFopMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.fop_group = cls.env.ref('l10n_ua_fop.fop_group_3')
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'fop_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id])],
        })

    def _book(self, company):
        return self.env['l10n_ua.fop.income.book'].create({
            'year': 2026, 'quarter': '1',
            'fop_group_id': self.fop_group.id,
            'company_id': company.id,
        })

    def test_other_company_user_cannot_see_ua_book(self):
        """A user of the non-UA company must not see the UA company's book."""
        book = self._book(self.company_ua)
        visible = self.env['l10n_ua.fop.income.book'].with_user(
            self.user_other).search([])
        self.assertNotIn(book, visible)

    def test_same_company_user_sees_own_book(self):
        """The rule still lets a user see their own company's book."""
        book = self._book(self.company_other)
        visible = self.env['l10n_ua.fop.income.book'].with_user(
            self.user_other).search([])
        self.assertIn(book, visible)

    def test_rules_exist_and_global(self):
        """Both multi-company rules are present and global."""
        for xmlid in (
            'l10n_ua_fop.l10n_ua_fop_declaration_company_rule',
            'l10n_ua_fop.l10n_ua_fop_income_book_company_rule',
        ):
            rule = self.env.ref(xmlid)
            self.assertEqual(
                rule.kind, 'restriction',
                '%s must be a restriction' % xmlid)
