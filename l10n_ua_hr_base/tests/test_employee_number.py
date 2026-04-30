from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError

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

    def test_03_employee_number_generation(self):
        """
        Check automatic generation (if implemented via ir.sequence).
        If there is no generation, this test can be removed.
        """
        employee_3 = self.env['hr.employee'].create({
            'name': 'Ivan Mazepa',
            'company_id': self.company_1.id,
            # Do not specify employee_number
        })
        # Replace 'New' with your default value if it is different
        self.assertTrue(employee_3.employee_number, "Employee number should be generated automatically")
