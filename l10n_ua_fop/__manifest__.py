{
    'name': 'Ukraine - FOP (Single Tax)',
    'version': '20.0.3.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Єдиний податок для ФОП: книга доходів, декларація, ЄСВ',
    'description': """
Ukraine FOP Module (Єдиний податок ФОП)
========================================

Модуль обліку єдиного податку для фізичних осіб-підприємців (ФОП):

* Книга обліку доходів (поквартально)
* Декларація платника єдиного податку (групи 1, 2, 3)
* Автоматичний розрахунок ЄП та ЄСВ
* Контроль ліміту доходу
* Друковані форми

Групи єдиного податку:
* Група 1 — фіксована ставка (до 10% прожиткового мінімуму)
* Група 2 — фіксована ставка (до 20% мінімальної зарплати)
* Група 3 без ПДВ — 5% від доходу
* Група 3 з ПДВ — 3% від доходу + ПДВ
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_tax',
        'l10n_ua_doc_reports',
        'l10n_ua_tax_F0103309',
        'l10n_ua_sign',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/l10n_ua_fop_group_data.xml',
        'views/l10n_ua_fop_income_book_views.xml',
        'views/l10n_ua_fop_declaration_views.xml',
        'views/menu_views.xml',
        'report/income_book_report.xml',
        'report/declaration_report.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
