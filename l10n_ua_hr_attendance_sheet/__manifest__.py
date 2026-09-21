{
    'name': 'Ukraine - HR Attendance Sheet',
    'version': '20.0.1.1.0',
    'category': 'Human Resources/Localization',
    'summary': 'Ukrainian attendance sheet (Табель обліку робочого часу)',
    'description': """
Ukraine HR Attendance Sheet Module
==================================

Attendance sheet management for Ukrainian localization (Табель П-5):

* Monthly timesheet (Табель обліку робочого часу)
* Standard Ukrainian timesheet codes (Я, В, Х, ВД, etc.)
* Automatic timesheet generation
* Integration with holidays and sick leaves
* Production calendar support
* Night hours tracking
* Overtime tracking
* Timesheet report (form П-5)

Requires l10n_ua_hr_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_holidays',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/hr_timesheet_code_data.xml',
        'views/hr_timesheet_views.xml',
        'views/hr_timesheet_code_views.xml',
        'views/hr_production_calendar_views.xml',
        'views/menu_views.xml',
        'report/hr_attendance_sheet_report.xml',
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
