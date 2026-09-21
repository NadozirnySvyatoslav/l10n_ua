{
    'name': 'Ukraine - Budget КПКВК Bulk Import',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Імпорт довідника КПКВК з CSV/DBF Казначейства',
    'description': """
КПКВК Bulk Import
=================

Wizard для масового завантаження довідника програмної класифікації
видатків (КПКВК) з файлів, які надає Держказначейство.

* CSV з UTF-8 (`code,name,year`)
* DBF — через залежність на `l10n_ua_budget_treasury_dbf` (опційно)

Як отримати актуальний довідник:
1. https://www.treasury.gov.ua/file-storage/normativno-dovidkova-informatsiya
2. Завантажити архів з .dbf файлами
3. Імпортувати через цей wizard

КПКВК оновлюються щороку — рекомендується завантажувати свіжий
довідник на початку кожного бюджетного року.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_budget_base',
    ],
    'data': [
        'security/ir.access.csv',
        'wizard/l10n_ua_kpkvk_import_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
