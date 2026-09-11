"""Common test setup for l10n_ua_hr_contract tests."""

from datetime import date, timedelta
from odoo.tests import TransactionCase


class ContractTestCase(TransactionCase):
    """Base test class with shared setup for contract tests."""

    _version_counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.department = cls.env['hr.department'].create({
            'name': 'Test IT Department',
            'company_id': cls.company.id,
        })

        cls.job = cls.env['hr.job'].create({
            'name': 'Програміст',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
        })

        cls.job_2 = cls.env['hr.job'].create({
            'name': 'Аналітик',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
        })

        # Create or find allowance types
        cls.allowance_seniority = cls.env['hr.allowance.type'].create({
            'name': 'За вислугу років',
            'code': 'TEST_SENIORITY',
            'category': 'seniority',
            'is_taxable': True,
            'is_esv_base': True,
            'default_percent': 10.0,
        })

        cls.allowance_hazard = cls.env['hr.allowance.type'].create({
            'name': 'За шкідливі умови',
            'code': 'TEST_HAZARD',
            'category': 'hazard',
            'is_taxable': True,
            'is_esv_base': True,
            'default_percent': 20.0,
        })

    def _create_employee(self, name=None):
        """Create a unique employee for testing."""
        ContractTestCase._version_counter += 1
        if name is None:
            name = f'Test Employee {ContractTestCase._version_counter}'
        return self.env['hr.employee'].create({
            'name': name,
            'company_id': self.company.id,
            'department_id': self.department.id,
            'job_id': self.job.id,
        })

    def _create_version(self, employee=None, **kwargs):
        """Helper to create an hr.version (contract version)."""
        if employee is None:
            employee = self._create_employee()
        ContractTestCase._version_counter += 1
        # Use unique date_version to avoid constraint violation
        unique_date = date(2025, 1, 1) + timedelta(days=ContractTestCase._version_counter)
        vals = {
            'employee_id': employee.id,
            'contract_date_start': date(2025, 1, 15),
            'date_version': unique_date,
            'wage': 25000,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': self.company.id,
        }
        vals.update(kwargs)
        return self.env['hr.version'].create(vals)
