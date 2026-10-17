"""Узгодженість компанії відділу і рахунку витрат на ЗП (issue #350)."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDepartmentExpenseAccountCompany(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env['res.company'].create({'name': 'UA Co A #350'})
        cls.company_b = cls.env['res.company'].create({'name': 'UA Co B #350'})
        # Користувач працює в компанії B, але бачить обидві компанії.
        cls.env = cls.env(context=dict(
            cls.env.context,
            allowed_company_ids=[cls.company_b.id, cls.company_a.id],
        ))
        Account = cls.env['account.account']
        cls.account_a = Account.with_company(cls.company_a).create({
            'code': '9101350', 'name': 'Expense A',
            'account_type': 'expense', 'company_ids': [(6, 0, cls.company_a.ids)],
        })
        cls.account_b = Account.with_company(cls.company_b).create({
            'code': '9102350', 'name': 'Expense B',
            'account_type': 'expense', 'company_ids': [(6, 0, cls.company_b.ids)],
        })
        cls.account_ab = Account.with_company(cls.company_a).create({
            'code': '9103350', 'name': 'Expense A+B',
            'account_type': 'expense', 'company_ids': [(6, 0, cls.company_a.ids)],
        })
        # Код рахунку має бути заданий для кожної компанії рахунку.
        cls.account_ab.with_company(cls.company_b).code = '9103350'
        cls.account_ab.company_ids = [(4, cls.company_b.id)]
        cls.Department = cls.env['hr.department']

    def test_field_check_company(self):
        self.assertTrue(
            self.Department._fields['salary_expense_account_id'].check_company)

    def test_create_with_foreign_account_rejected(self):
        with self.assertRaises(UserError):
            self.Department.create({
                'name': 'Dept A',
                'company_id': self.company_a.id,
                'salary_expense_account_id': self.account_b.id,
            })

    def test_write_foreign_account_rejected(self):
        dept = self.Department.create({'name': 'Dept A', 'company_id': self.company_a.id})
        with self.assertRaises(UserError):
            dept.write({'salary_expense_account_id': self.account_b.id})

    def test_same_company_account_ok(self):
        dept = self.Department.create({
            'name': 'Dept A',
            'company_id': self.company_a.id,
            'salary_expense_account_id': self.account_a.id,
        })
        self.assertEqual(dept.salary_expense_account_id, self.account_a)

    def test_shared_account_ok(self):
        dept = self.Department.create({
            'name': 'Dept A',
            'company_id': self.company_a.id,
            'salary_expense_account_id': self.account_ab.id,
        })
        self.assertEqual(dept.salary_expense_account_id, self.account_ab)

    def test_department_without_company_accepts_any_account(self):
        dept = self.Department.create({
            'name': 'Shared Dept',
            'company_id': False,
            'salary_expense_account_id': self.account_b.id,
        })
        self.assertEqual(dept.salary_expense_account_id, self.account_b)

    def test_change_company_with_account_rejected(self):
        dept = self.Department.create({
            'name': 'Dept A',
            'company_id': self.company_a.id,
            'salary_expense_account_id': self.account_a.id,
        })
        with self.assertRaises(UserError):
            dept.write({'company_id': self.company_b.id})
