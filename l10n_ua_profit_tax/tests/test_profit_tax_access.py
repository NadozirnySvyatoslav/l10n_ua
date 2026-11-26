from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_profit_tax')
class TestProfitTaxAccess(TransactionCase):
    """Odoo 20 port: ir.model.access + global ir.rule were converted to ir.access.

    The multi-company record must stay a restriction, and the accountant keeps
    the 19.0 rights (create/read/write, no delete; delete — accounting manager)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Profit tax other company'})
        cls.accountant = cls.env['res.users'].create({
            'name': 'Profit tax accountant', 'login': 'profit_tax_accountant',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, cls.env.ref('account.group_account_user').ids)],
        })
        Declaration = cls.env['l10n_ua.profit.tax.declaration']
        cls.own = Declaration.create({'company_id': cls.company.id, 'year': 2046, 'period': 'q1'})
        cls.foreign = Declaration.create(
            {'company_id': cls.other_company.id, 'year': 2046, 'period': 'q1'})

    def test_company_record_is_restriction(self):
        accesses = self.env['ir.access'].search([
            ('model_id.model', '=', 'l10n_ua.profit.tax.declaration'), ('group_id', '=', False)])
        self.assertEqual(accesses.mapped('kind'), ['restriction'])

    def test_accountant_sees_only_own_company(self):
        Declaration = self.env['l10n_ua.profit.tax.declaration'].with_user(self.accountant)
        self.assertEqual(Declaration.search([('id', 'in', (self.own | self.foreign).ids)]),
                         self.own.with_user(self.accountant))

    def test_accountant_cannot_delete(self):
        self.own.with_user(self.accountant).write({'period': 'h1'})
        with self.assertRaises(AccessError):
            self.own.with_user(self.accountant).unlink()
