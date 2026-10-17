"""Узгодженість компанії відділу і його керівника (issue #350)."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDepartmentHeadCompany(TransactionCase):

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
        Employee = cls.env['hr.employee']
        cls.emp_a = Employee.create({'name': 'Head A', 'company_id': cls.company_a.id})
        cls.emp_b = Employee.create({'name': 'Head B', 'company_id': cls.company_b.id})
        cls.Department = cls.env['hr.department']

    def test_field_check_company(self):
        self.assertTrue(self.Department._fields['head_employee_id'].check_company)

    def test_create_with_foreign_head_rejected(self):
        with self.assertRaises(UserError):
            self.Department.create({
                'name': 'Dept A',
                'company_id': self.company_a.id,
                'head_employee_id': self.emp_b.id,
            })

    def test_write_foreign_head_rejected(self):
        dept = self.Department.create({'name': 'Dept A', 'company_id': self.company_a.id})
        with self.assertRaises(UserError):
            dept.write({'head_employee_id': self.emp_b.id})

    def test_same_company_head_ok(self):
        dept = self.Department.create({
            'name': 'Dept A',
            'company_id': self.company_a.id,
            'head_employee_id': self.emp_a.id,
        })
        self.assertEqual(dept.head_employee_id, self.emp_a)

    def test_department_without_company_rejects_company_head(self):
        # Стандартна семантика check_company для hr.employee: відділу без
        # компанії відповідають лише записи без компанії (так само звужується
        # і список вибору у формі). Працівник завжди має компанію.
        with self.assertRaises(UserError):
            self.Department.create({
                'name': 'Shared Dept',
                'company_id': False,
                'head_employee_id': self.emp_b.id,
            })

    def test_change_company_with_head_rejected(self):
        dept = self.Department.create({
            'name': 'Dept A',
            'company_id': self.company_a.id,
            'head_employee_id': self.emp_a.id,
        })
        with self.assertRaises(UserError):
            dept.write({'company_id': self.company_b.id})
