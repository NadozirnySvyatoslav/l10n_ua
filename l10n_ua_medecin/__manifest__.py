{
    'name': 'Ukraine - Medecin (Усе для закладів охорони здоров\'я)',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Umbrella: повний стек для медичних закладів України',
    'description': """
Ukraine Medecin Suite
=====================

Umbrella, що встановлює повний набір модулів для українських медичних
закладів (ЦПМСД, АСМД, поліклінік, лікарень, ЕМД, діагностичних центрів):

* `l10n_ua_medecin_base` — типи закладів, ліцензії МОЗ, спеціалізації
* `l10n_ua_medecin_patient` — пацієнти + декларації з лікарем ПМД
* `l10n_ua_medecin_nszu` — договори НСЗУ + пакети медичних послуг + капітація

Для повного бюджетного циклу — додатково встановити `l10n_ua_budget`.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_base',
        'l10n_ua_medecin_patient',
        'l10n_ua_medecin_nszu',
    ],
    'data': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
