{
    'name': 'Ukraine - Business Trip Report (Звіт про відрядження)',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Звіт про відрядження: добові за нормами, проїзд/проживання, '
               'друкована форма, зв’язок з наказом та авансовим звітом',
    'description': """
Ukraine Business Trip Report
============================

Звіт про службове відрядження поверх наказу (``hr.order`` типу business_trip)
та авансового звіту (``l10n_ua.advance.report``):

* Прив'язка до наказу на відрядження;
* Добові за нормами × кількість днів (норма — налаштування компанії);
* Витрати на проїзд та проживання;
* Друкована форма звіту про відрядження;
* Формування авансового звіту (підзвіт) із звіту про відрядження.

Міст між ``l10n_ua_hr_documents`` та ``l10n_ua_accounting``.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_documents',
        'l10n_ua_accounting',
    ],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/res_company_views.xml',
        'views/business_trip_report_views.xml',
        'report/business_trip_report_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
