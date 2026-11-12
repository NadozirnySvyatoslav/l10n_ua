{
    'name': 'Ukraine - Corporate Profit Tax Declaration',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Податкова декларація з податку на прибуток підприємств (J0100129) з додатком РІ',
    'description': """
Декларація з податку на прибуток підприємств
============================================

Форма за наказом Мінфіну № 897 у редакції наказу № 101 (зі змінами, наказ № 371
від 25.07.2025), XML J0100129 з додатком РІ (J0111829):

* дохід (рядок 01) і фінансовий результат до оподаткування (рядок 02) — з бухобліку
  за правилами Звіту про фінансові результати, наростаючим підсумком з 1 січня;
* податкові різниці додатка РІ вносить бухгалтер; рішення не застосовувати коригування
  (пп. 134.1.1 ПКУ) для платників з доходом до 40 млн грн;
* об'єкт оподаткування, податок за ставкою 18 %, податок попереднього періоду року
  для квартальних платників і податок до нарахування за останній квартал;
* перевірка офіційною XSD-схемою ДПС, підпис КЕП у браузері й подання через
  Електронний кабінет.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_accounting',
        'l10n_ua_tax',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'views/l10n_ua_profit_tax_declaration_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
