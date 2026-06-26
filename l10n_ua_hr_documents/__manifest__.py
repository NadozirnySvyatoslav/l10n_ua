{
    'name': 'Ukraine - HR Documents',
    'version': '19.0.1.0.1',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian HR document templates and orders',
    'description': """
Ukraine HR Documents Module
===========================

HR document management for Ukrainian localization:

* HR orders (Накази) - hiring, transfer, termination, vacation, bonus, etc.
* HR order templates with placeholders
* Document numbering sequences
* Employee personal file management
* Document templates with Ukrainian formatting
* Order printing (Накази)
* Personal card (Особова картка П-2)
* Employment history book entries

Requires l10n_ua_hr_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_contract',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/hr_order_security.xml',
        'data/ir_sequence_data.xml',
        'data/hr_order_type_data.xml',
        'data/hr_order_template_data.xml',
        'views/hr_order_views.xml',
        'views/hr_order_template_views.xml',
        'wizard/hr_order_template_wizard_views.xml',
        'views/hr_order_type_views.xml',
        'views/hr_personal_file_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
        'report/hr_order_report.xml',
    ],
    'demo': [
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
