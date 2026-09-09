{
    'name': 'Ukraine - HR Salary',
    'version': '19.0.1.4.2',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian salary calculation',
    'description': """
Ukraine HR Salary Module
========================

Payroll calculation for Ukrainian localization:

* Salary calculation based on worked days/hours
* PDFO (personal income tax) - 18%
* Military tax - 5%
* ESV (unified social contribution) - 22%
* PSP (tax social benefit) calculation
* Allowances and bonuses
* Deductions (alimony, union fees, etc.)
* Execution documents support
* Salary advance (аванс) management
* Minimum wage validation
* Maximum ESV base (15 minimum wages)
* Payslip generation and printing
* Bank payment registers

Requires l10n_ua_hr_base module. Uses hr.version from Odoo 19.

Note: This module was renamed from l10n_ua_hr_payroll to l10n_ua_hr_salary
to avoid naming conflicts with existing modules on Odoo Apps.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_contract',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'data/hr_accrual_type_data.xml',
        'data/hr_deduction_type_data.xml',
        'data/hr_psp_parameters_data.xml',
        'data/hr_seniority_scale_data.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/hr_accrual_type_views.xml',
        'views/hr_deduction_type_views.xml',
        'views/hr_psp_parameters_views.xml',
        'views/hr_cpi_index_views.xml',
        'views/hr_seniority_scale_views.xml',
        'views/hr_piece_work_entry_views.xml',
        'views/hr_version_views.xml',
        'views/hr_execution_document_views.xml',
        'views/hr_salary_advance_views.xml',
        'views/hr_salary_advance_run_views.xml',
        'views/menu_views.xml',
        'views/hr_salary_deposit_views.xml',
        'views/res_company_views.xml',
        'wizard/hr_payslip_bank_export_views.xml',
        'wizard/hr_ifobs_employee_export_views.xml',
        'report/hr_payslip_report.xml',
    ],
    'demo': [
        'demo/hr_payroll_demo.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
