{
    'name': 'Ukraine - HR Salary Bonus',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Bonus management for Ukrainian payroll',
    'description': """
Ukraine - HR Salary Bonus
=========================

This module adds bonus management functionality to Ukrainian payroll:

* Bonus types with tax settings (PDFO, Military Tax, ESV)
* Bonus records linked to employees
* Integration with payslip calculation
* Workflow: Draft → Confirmed → Paid

Bonuses are automatically included in salary calculation when:
- Employee has bonus system enabled
- Bonus is in 'confirmed' state
- Bonus date falls within payslip period
    """,
    'author': 'NDEV',
    'website': 'https://ndev.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_salary',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'data/hr_bonus_type_data.xml',
        'views/hr_bonus_type_views.xml',
        'views/hr_bonus_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
