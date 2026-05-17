{
    'name': 'Ukraine - HR Holidays',
    'version': '19.0.1.0.2',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian holidays and sick leave management',
    'description': """
Ukraine HR Holidays Module
==========================

Holidays and sick leave management for Ukrainian localization:

* Vacation types according to Ukrainian law (annual, additional, educational, unpaid)
* Vacation balance tracking per employee
* Vacation schedule (yearly planning)
* Sick leave management (e-TVN support)
* Sick leave payment calculation (employer + FSS)
* Average salary calculation for vacation pay
* Maternity leave support
* Vacation compensation on termination

Requires l10n_ua_hr_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'pre_init_hook': 'pre_init_hook',
    'depends': [
        'hr_holidays',
        'resource',
        'l10n_ua_hr_base',
        'l10n_ua_hr_documents',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_vacation_balance_security.xml',
        'data/hr_sick_leave_data.xml',
        'data/hr_leave_type_data.xml',
        'data/hr_public_holiday_data.xml',
        'views/res_company_views.xml',
        'views/hr_leave_views.xml',
        'views/hr_leave_type_views.xml',
        'views/hr_sick_leave_views.xml',
        'views/hr_vacation_balance_views.xml',
        'views/hr_vacation_schedule_views.xml',
        'views/hr_employee_vacation_summary_report_views.xml',
        'views/menu_views.xml',
        'report/hr_leave_report.xml',
        'report/hr_employee_vacation_summary_report.xml',
    ],
    'demo': [
        'demo/hr_holidays_demo.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
