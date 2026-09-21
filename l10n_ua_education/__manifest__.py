{
    'name': 'Ukraine - Education (Усе для закладів освіти)',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Education',
    'summary': 'Umbrella: повний стек для українських освітніх установ',
    'description': """
Ukraine Education Suite
=======================

Umbrella, що встановлює повний набір модулів для українських освітніх
установ (ЗДО, ЗЗСО, ліцеї, ПТУ, ЗВО I-IV рівнів):

* `l10n_ua_education_base` — типи закладів, контингент, навчальні групи, навчальні роки
* `l10n_ua_education_scholarship` — типи стипендій і відомості виплати
* `l10n_ua_education_edebo` — імпорт/експорт у ЄДЕБО (CSV-каркас)

Для повного бюджетного циклу — додатково установити `l10n_ua_budget`.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_education_base',
        'l10n_ua_education_scholarship',
        'l10n_ua_education_edebo',
    ],
    'data': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
