{
    'name': 'Ukraine - Budget Estimate (Кошториси)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Кошториси бюджетних установ: план асигнувань і контроль виконання',
    'description': """
Ukraine Budget Estimate
=======================

Модуль кошторисів (кошторис, план асигнувань) для українських бюджетних
установ. Будується поверх `l10n_ua_budget_base`.

* Документ «Кошторис» з державною машиною: draft → submitted → approved → executed → closed
* Рядки кошторису з аналітикою КЕКВ × Фонд × Період (рік/квартал/місяць)
* Розпис на 12 місяців і 4 квартали з автоматичною перевіркою балансу
* Автоматичний підрахунок касового виконання з `account.move.line`
  (фільтр по році, КЕКВ, фонду, КПКВК) — план vs факт, % виконання,
  залишок асигнувань
* Окремий розрахунок по загальному / спеціальному фондах
* Зміни до кошторису (довідки про зміни) як версії документа

Не входить (у наступних модулях):
* `l10n_ua_budget_treasury` — інтеграція з ДКСУ, реєстраційні рахунки
* `l10n_ua_budget_reports` — друк форми кошторису, план використання

Регуляторна база: Бюджетний кодекс ст. 75, Наказ Мінфіну № 44 від
28.01.2002 «Про порядок складання, розгляду, затвердження та основні
вимоги до виконання кошторисів» (актуальна редакція — звіряти на rada).
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_budget_base',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'views/l10n_ua_budget_estimate_views.xml',
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
