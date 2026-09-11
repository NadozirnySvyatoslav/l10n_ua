"""Common test setup for l10n_ua_hr_salary tests."""

from datetime import date, timedelta
from odoo.tests import TransactionCase


class SalaryTestCase(TransactionCase):
    """Base test class with shared setup for salary tests."""

    _counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Тестова компанія Odoo за замовчуванням у доларах, а весь цей набір
        # тестів — про українську зарплату: мінімалка 8000, прожитковий
        # мінімум 3028, ПСП і ЄСВ рахуються від гривневих порогів. Найгірше
        # це збивало тести валютного окладу: в доларовій компанії оклад у
        # доларах не іноземний, конвертувати нема чого, і три тести падали
        # на продукті, який працює правильно.
        cls.uah = cls.env.ref('base.UAH')
        cls.company.write({'currency_id': cls.uah.id})

        cls.department = cls.env['hr.department'].create({
            'name': 'Відділ розробки',
            'company_id': cls.company.id,
        })

        cls.job = cls.env['hr.job'].create({
            'name': 'Розробник',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Петренко Олександр Миколайович',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })

        # Create version (contract) for employee with unique date_version
        SalaryTestCase._counter += 1
        cls.version = cls.env['hr.version'].create({
            'employee_id': cls.employee.id,
            'contract_date_start': date(2024, 1, 15),
            'date_version': date(2024, 1, 15),
            'wage': 25000,
            'contract_type_ua': 'permanent',
            'employment_type_ua': 'primary',
            'company_id': cls.company.id,
        })
        cls.employee.write({'current_version_id': cls.version.id})

        # Find or create PSP parameters for 2025
        cls.psp_params = cls.env['hr.psp.parameters'].search([
            ('year', '=', 2025),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.psp_params:
            cls.psp_params = cls.env['hr.psp.parameters'].create({
                'year': 2025,
                'date_from': date(2025, 1, 1),
                'subsistence_minimum': 3028,
                'min_wage': 8000,
                'company_id': cls.company.id,
            })

        # Create accrual types
        cls.accrual_wage = cls.env['hr.accrual.type'].search([
            ('category', '=', 'wage'),
        ], limit=1)
        if not cls.accrual_wage:
            cls.accrual_wage = cls.env['hr.accrual.type'].create({
                'name': 'Основна заробітна плата',
                'code': 'WAGE',
                'category': 'wage',
                'is_basic_salary': True,
                'is_taxable_pdfo': True,
                'is_military_tax': True,
                'is_esv_base': True,
            })

        # Create deduction types
        cls.deduction_pdfo = cls.env['hr.deduction.type'].search([
            ('category', '=', 'tax'),
        ], limit=1)
        if not cls.deduction_pdfo:
            cls.deduction_pdfo = cls.env['hr.deduction.type'].create({
                'name': 'ПДФО',
                'code': 'PDFO',
                'category': 'tax',
                'calculation_method': 'percent_gross',
            })
