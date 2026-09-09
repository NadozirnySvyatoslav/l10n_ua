{
    'name': 'Ukraine - HR Reports',
    'version': '19.0.1.0.1',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian HR regulatory reports',
    'description': """
Ukraine HR Reports Module
=========================

Regulatory reports for Ukrainian localization:

* 1DF (Quarterly tax report)
* 4DF (Monthly tax report)
* D5 (ESV monthly report)
* D1 (ESV appendix - employee data)
* Statistical reports (1-PV, 3-PV)
* Average headcount calculation
* Wage fund reports

Requires l10n_ua_hr_salary module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_salary',
        'l10n_ua_sign',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'views/hr_report_1df_views.xml',
        'views/hr_report_d5_views.xml',
        'views/hr_report_headcount_views.xml',
        'views/hr_report_wage_fund_views.xml',
        'wizard/hr_report_wizard_views.xml',
        'views/menu_views.xml',
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
