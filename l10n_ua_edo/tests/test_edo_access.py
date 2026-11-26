from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdoAccess(TransactionCase):
    """Odoo 20 port: ir.model.access + global ir.rule were converted to ir.access.

    The multi-company records must stay restrictions, and a plain user keeps
    the 19.0 rights (read accounts/categories, no write)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'EDO other company'})
        cls.user = cls.env['res.users'].create({
            'name': 'EDO user', 'login': 'edo_access_user',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
        })
        Account = cls.env['l10n_ua.edo.account']
        cls.own_account = Account.create({'name': 'Own EDO', 'company_id': cls.company.id})
        cls.foreign_account = Account.create({'name': 'Foreign EDO', 'company_id': cls.other_company.id})
        Category = cls.env['l10n_ua.edo.category']
        cls.own_category = Category.create({'account_id': cls.own_account.id, 'code': '1', 'name': 'Own'})
        cls.foreign_category = Category.create(
            {'account_id': cls.foreign_account.id, 'code': '1', 'name': 'Foreign'})

    def test_company_records_are_restrictions(self):
        models = ['l10n_ua.edo.account', 'l10n_ua.edo.document',
                  'l10n_ua.edo.category', 'l10n_ua.edo.category.rule']
        for model in models:
            accesses = self.env['ir.access'].search(
                [('model_id.model', '=', model), ('group_id', '=', False)])
            self.assertEqual(accesses.mapped('kind'), ['restriction'], model)

    def test_user_sees_only_own_company(self):
        Account = self.env['l10n_ua.edo.account'].with_user(self.user)
        Category = self.env['l10n_ua.edo.category'].with_user(self.user)
        self.assertEqual(Account.search([('id', 'in', (self.own_account | self.foreign_account).ids)]),
                         self.own_account.with_user(self.user))
        self.assertEqual(Category.search([('id', 'in', (self.own_category | self.foreign_category).ids)]),
                         self.own_category.with_user(self.user))

    def test_user_cannot_edit_account(self):
        with self.assertRaises(AccessError):
            self.own_account.with_user(self.user).write({'name': 'Changed'})
