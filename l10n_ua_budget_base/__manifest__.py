{
    'name': 'Ukraine - Budget Base (Public Sector)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Foundation for Ukrainian public-sector accounting: budget classifications and fund accounting',
    'description': """
Ukraine Budget Base
===================

Foundation module for Ukrainian public-sector (бюджетні установи) accounting.

Provides the building blocks required by every state-sector module — budget
classifications, fund accounting (загальний/спеціальний фонд), and analytical
tagging on accounts and journal entries:

* Економічна класифікація видатків (КЕКВ) — hierarchical
* Функціональна класифікація (КФК) — hierarchical
* Програмна класифікація видатків (КПКВК)
* Відомча класифікація (КВКВ) — chief spending unit
* Фонд (Selection: загальний / спеціальний)
* Extensions on account.account / account.move.line to tag КЕКВ/КФК/КПКВК/КВКВ/Фонд

Does NOT include: estimates (cf. l10n_ua_budget_estimate), treasury integration
(cf. l10n_ua_budget_treasury), budget reporting forms (cf. l10n_ua_budget_reports).

Regulatory basis: Бюджетний кодекс України, Наказ Мінфіну № 1203 від
31.12.2013, Наказ Мінфіну № 11 від 14.01.2011, Наказ Мінфіну № 333 від
12.03.2012. Always cross-check active redactions on rada.gov.ua.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_account_base',
    ],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/l10n_ua.kvkv.csv',
        'data/l10n_ua.kfk.csv',
        'data/l10n_ua.kekv.csv',
        'data/l10n_ua.kpkvk.csv',
        'views/l10n_ua_kekv_views.xml',
        'views/l10n_ua_kfk_views.xml',
        'views/l10n_ua_kpkvk_views.xml',
        'views/l10n_ua_kvkv_views.xml',
        'views/account_account_views.xml',
        'views/account_move_views.xml',
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
