{
    'name': 'Ukraine - HR Base',
    'version': '19.0.1.0.1',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian HR localization base module',
    'description': """
Ukraine HR Base Module
======================

Base module for Ukrainian HR localization providing:

* Employee personal documents (RNOKPP/IPN, passport, ID card)
* Registration and actual addresses
* Education information
* Military accounting
* Benefits and disability tracking
* Family members and children
* Department extensions (KOATUU, separate units)
* Job positions with KP-2010 classifier
* Staffing table (штатний розпис)
* Reference data (military ranks, TCC, education levels, tariff grades)

This module is required for all other l10n_ua_hr_* modules.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'hr',
    ],
    'data': [
        'security/hr_ua_security.xml',
        'security/ir.model.access.csv',
        'data/hr_education_level_data.xml',
        'data/hr_military_rank_data.xml',
        'data/hr_employee_benefit_data.xml',
        'data/hr_tariff_grade_data.xml',
        'data/hr_kp2010_data.xml',
        'data/res_country_state.xml',
        'data/hr_military_tcc_data.xml',
        'data/ir_sequence_data.xml',
        'data/report_paperformat_data.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_child_views.xml',
        'views/hr_department_views.xml',
        'views/hr_job_views.xml',
        'views/hr_staffing_table_views.xml',
        'views/hr_employee_reports_views.xml',
        'views/hr_military_rank_views.xml',
        'views/hr_military_tcc_views.xml',
        'views/hr_education_level_views.xml',
        'views/hr_employee_benefit_views.xml',
        'views/hr_tariff_grade_views.xml',
        'views/hr_kp2010_views.xml',
        'views/res_company_views.xml',
        'views/menu_views.xml',
        'report/hr_staffing_table_report.xml',
        'report/hr_employee_p2_report.xml',
        'report/hr_employee_list_report.xml',
        'report/hr_employee_military_report.xml',
        'report/hr_employee_benefits_report.xml',
        'report/hr_vacancies_report.xml',
    ],
    'demo': [
        'demo/hr_demo_data.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',

}
