{
    'name': 'Ukraine - Budget (Усе для бюджетних установ)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Umbrella: встановлює увесь стек для бюджетних установ',
    'description': """
Ukraine Budget Suite
====================

Umbrella-модуль, що одним кліком встановлює повний набір модулів для
ведення обліку в бюджетній установі України:

* `l10n_ua_budget_base` — класифікатори (КЕКВ / КФК / КПКВК / КВКВ), фонди
* `l10n_ua_budget_chart_template` — план рахунків Наказу 1203
* `l10n_ua_budget_estimate` — кошториси + контроль виконання
* `l10n_ua_budget_treasury` — ДКСУ + контроль ліміту асигнувань
* `l10n_ua_budget_reports` — друкована форма кошторису, форма 2д

Для конкретної галузі (освіта, медицина) — додатково установити
відповідну umbrella: `l10n_ua_education`, `l10n_ua_medecin`.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_budget_base',
        'l10n_ua_budget_chart_template',
        'l10n_ua_budget_estimate',
        'l10n_ua_budget_treasury',
        'l10n_ua_budget_reports',
    ],
    'data': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
