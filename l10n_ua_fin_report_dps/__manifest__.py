{
    'name': 'Ukraine - Financial Statements XML to DPS',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'XML of financial statements (J0900108, J0900207, J0901107, J0901205…) and filing to DPS',
    'description': """
Фінансова звітність до ДПС
==========================

XML за схемами ДПС і подання з КЕП через Електронний кабінет для звітів
l10n_ua_accounting:

* Баланс (J0900108), Звіт про фінансові результати (J0900207);
* Звіт про рух грошових коштів (J0900904 / J0901602), про власний капітал (J0901005);
* фінзвітність малого підприємства (J0901107) і мікропідприємства (J0901205).

Перед збереженням документ перевіряється офіційною XSD-схемою.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_accounting',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'views/fin_report_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
