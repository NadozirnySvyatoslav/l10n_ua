{
    'name': 'Ukraine - HR Complete',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Complete Ukrainian HR localization package',
    'description': """
Ukraine HR Complete Package
===========================

This is a meta-module that installs all Ukrainian HR localization modules:

* **l10n_ua_hr_base** - Base module with RNOKPP, security groups, demo data
* **l10n_ua_hr_contract** - Employment contracts (own model for Community edition)
* **l10n_ua_hr_salary** - Salary calculation (PDFO 18%, Military 5%, ESV 22%, PSP)
* **l10n_ua_hr_holidays** - Vacations and sick leaves (extends hr_holidays)
* **l10n_ua_hr_attendance_sheet** - Attendance sheet (Табель П-5), production calendar
* **l10n_ua_hr_documents** - HR orders, personal files
* **l10n_ua_hr_documents_certificates** - HR certificates (довідки)
* **l10n_ua_hr_reports** - Regulatory reports (1DF, D5)

Features:
---------
* Ukrainian tax calculation (PDFO, Military Tax, ESV)
* Tax Social Benefit (PSP) with automatic eligibility
* Contract types per Ukrainian Labor Code
* Termination reasons per Labor Code articles
* Vacation types and balance tracking
* Sick leave with FSS integration
* Execution documents (alimony)
* Monthly attendance sheet (form П-5)
* Production calendar with Ukrainian holidays
* HR orders with templates
* Personal files management
* Regulatory reports generation

This package is designed for Odoo 20 Community Edition.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
        'l10n_ua_hr_contract',
        'l10n_ua_hr_salary',
        'l10n_ua_hr_holidays',
        'l10n_ua_hr_attendance_sheet',
        'l10n_ua_hr_documents',
        'l10n_ua_hr_documents_certificates',
        'l10n_ua_hr_reports',
    ],
    'data': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
