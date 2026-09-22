"""Multi-company isolation for UA VAT documents — issue #178.

Without record rules the VAT documents were visible across ALL companies,
including non-UA ones. These tests assert the global multi-company rules scope
each document to the user's allowed companies.
"""

from datetime import date
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVatMultiCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env['res.company']
        cls.company_ua = Company.create({
            'name': 'UA Co (test)', 'country_id': cls.env.ref('base.ua').id})
        cls.company_other = Company.create({
            'name': 'Other Co (test)', 'country_id': cls.env.ref('base.fr').id})
        cls.partner = cls.env['res.partner'].create({
            'name': 'Buyer'})
        # user whose ONLY allowed company is the non-UA one
        cls.user_other = cls.env['res.users'].create({
            'name': 'Other User', 'login': 'vat_other_user',
            'company_id': cls.company_other.id,
            'company_ids': [(6, 0, [cls.company_other.id])],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id])],
        })

    def _invoice(self, company):
        return self.env['l10n_ua.tax.invoice'].create({
            'doc_type': 'pn', 'number': 'TN-1', 'date': date(2026, 2, 10),
            'invoice_type': 'issued', 'partner_id': self.partner.id,
            'company_id': company.id,
        })

    def test_other_company_user_cannot_see_ua_invoice(self):
        """A user of the non-UA company must not see the UA company's ПН."""
        inv = self._invoice(self.company_ua)
        visible = self.env['l10n_ua.tax.invoice'].with_user(self.user_other).search([])
        self.assertNotIn(inv, visible)

    def test_same_company_user_sees_own_invoice(self):
        """The rule still lets a user see their own company's ПН."""
        inv = self._invoice(self.company_other)
        visible = self.env['l10n_ua.tax.invoice'].with_user(self.user_other).search([])
        self.assertIn(inv, visible)
