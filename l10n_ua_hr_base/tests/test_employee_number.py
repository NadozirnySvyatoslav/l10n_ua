from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

@tagged('post_install', '-at_install')
class TestHrEmployeeNumber(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_1 = cls.env['res.company'].create({'name': 'Test Company 1'})
        cls.company_2 = cls.env['res.company'].create({'name': 'Test Company 2'})
        
        cls.employee_1 = cls.env['hr.employee'].create({
            'name': 'Taras Shevchenko',
            'company_id': cls.company_1.id,
            'employee_number': 'EMP-001',
        })

    def test_01_employee_number_uniqueness(self):
        """Check employee number uniqueness within the same company"""
        with self.assertRaises(ValidationError):
            self.env['hr.employee'].create({
                'name': 'Ivan Franko',
                'company_id': self.company_1.id,
                'employee_number': 'EMP-001', # Duplicate for company 1
            })

    def test_02_employee_number_multi_company(self):
        """Check that identical employee numbers are allowed in different companies"""
        employee_2 = self.env['hr.employee'].create({
            'name': 'Lesya Ukrainka',
            'company_id': self.company_2.id,
            'employee_number': 'EMP-001', # Same number, but different company
        })
        self.assertEqual(employee_2.employee_number, 'EMP-001')
