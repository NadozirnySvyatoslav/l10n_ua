from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAgreementAccess(TransactionCase):
    """Odoo 20 port: ir.model.access + global ir.rule were converted to ir.access.

    The multi-company record must stay a restriction; rights are the 19.0 ones:
    internal user reads, salesman creates/edits, sales manager deletes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env['res.company'].create({'name': 'Agreement other company'})
        cls.salesman = cls.env['res.users'].create({
            'name': 'Agreement salesman', 'login': 'agreement_salesman',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, cls.env.ref('sales_team.group_sale_salesman').ids)],
        })
        cls.employee = cls.env['res.users'].create({
            'name': 'Agreement employee', 'login': 'agreement_employee',
            'company_id': cls.company.id, 'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, cls.env.ref('base.group_user').ids)],
        })
        partner = cls.env['res.partner'].create({'name': 'ТОВ Клієнт', 'is_company': True})
        Agreement = cls.env['l10n_ua.agreement']
        cls.own = Agreement.create({'name': 'Own', 'partner_id': partner.id,
                                    'company_id': cls.company.id})
        cls.foreign = Agreement.create({'name': 'Foreign', 'partner_id': partner.id,
                                        'company_id': cls.other_company.id})

    def test_company_record_is_restriction(self):
        accesses = self.env['ir.access'].search([
            ('model_id.model', '=', 'l10n_ua.agreement'), ('group_id', '=', False)])
        self.assertEqual(accesses.mapped('kind'), ['restriction'])

    def test_salesman_sees_only_own_company(self):
        Agreement = self.env['l10n_ua.agreement'].with_user(self.salesman)
        self.assertEqual(Agreement.search([('id', 'in', (self.own | self.foreign).ids)]),
                         self.own.with_user(self.salesman))

    def test_salesman_edits_but_cannot_delete(self):
        self.own.with_user(self.salesman).write({'subject': 'Changed'})
        with self.assertRaises(AccessError):
            self.own.with_user(self.salesman).unlink()

    def test_employee_reads_only(self):
        self.assertEqual(self.own.with_user(self.employee).name, 'Own')
        with self.assertRaises(AccessError):
            self.own.with_user(self.employee).write({'subject': 'Changed'})
