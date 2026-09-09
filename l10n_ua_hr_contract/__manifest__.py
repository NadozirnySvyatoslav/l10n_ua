{
    'name': 'Ukraine - HR Contracts',
    'version': '19.0.7.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian HR contracts localization (extends hr.version)',
    'description': """
Ukraine HR Contracts Module
===========================

Extension of hr.version for Ukrainian localization (Odoo 19 architecture):

* Contract types (permanent, fixed-term, civil, gig-contract)
* Main workplace / part-time work tracking
* Work modes (full-time, part-time, flexible, remote)
* Work schedules via native resource.calendar
* Probation period management
* Version allowances (seniority, hazard, intensity)
* Termination reasons according to Ukrainian Labor Code
* Staffing table integration
* Tariff grade support
* Diia.City employee support
* Job combining management

Uses native Odoo 19 hr.version model instead of separate hr.contract.

Requires l10n_ua_hr_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'resource',   # explicit: we now inherit resource.calendar
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'data/hr_allowance_type_data.xml',
        'data/resource_calendar_ua_data.xml',
        'data/hr_termination_reason_data.xml',
        'views/hr_allowance_type_views.xml',
        'views/hr_employee_reports_views.xml',
        'views/hr_version_allowance_views.xml',
        'views/hr_version_views.xml',
        'views/hr_version_salary_change_views.xml',
        'views/hr_job_combining_views.xml',
        'views/hr_version_amendment_views.xml',
        'views/resource_calendar_views.xml',
        'views/hr_termination_reason_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
        'report/hr_employee_list_report_inherit.xml',
    ],
    'demo': [
    ],
    'post_init_hook': 'post_init_hook',
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
