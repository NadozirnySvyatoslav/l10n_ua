{
    'name': 'Ukraine - HR Vacation Reserve',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Резерв відпусток: автоматичне нарахування проводок (П(С)БО 26)',
    'description': """
Ukraine HR Vacation Reserve Module
==================================

Automatic accrual of vacation reserve provisions per П(С)БО 26
«Виплати працівникам» and ст. 23.4 ПКУ.

* Monthly cron-driven accrual of vacation reserve per active employee
* Accrual entries: Дт 23 / 91 / 92 / 93 (expense per function) / Кт 471
* Reversal entries on actual vacation payment: Дт 471 / Кт 661
* Configurable expense accounts per hr.job and hr.employee
* Configurable journal, periodicity, and default 471/661 accounts on company
* History of monthly reserve documents with line per employee

Requires l10n_ua_hr_holidays, l10n_ua_hr_salary, and account modules.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_hr_holidays',
        'l10n_ua_hr_salary',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/res_company_views.xml',
        'views/hr_job_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_vacation_reserve_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
