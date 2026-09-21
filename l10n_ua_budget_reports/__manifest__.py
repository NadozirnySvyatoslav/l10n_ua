{
    'name': 'Ukraine - Budget Reports',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Друковані форми кошторису, звіти 2д/4-1д, меморіальні ордери',
    'description': """
Ukraine Budget Reports
======================

Друковані форми та офіційна звітність для українських бюджетних установ.

* Кошторис (Наказ Мінфіну № 44 від 28.01.2002) — друкована форма
  з рядками за КЕКВ × фонд × квартали, місце для підписів.
* Форма 2д «Звіт про надходження та використання коштів загального фонду»
  з wizard-параметром періоду (квартал / рік).
* Місця для розширень: форми 4-1д / 7д / 9д, меморіальні ордери 1-17
  буде додано окремими PR-ами.

Регуляторна база:
* Наказ Мінфіну № 44 від 28.01.2002 — кошториси
* Наказ Мінфіну № 44 від 24.01.2012 — звітність розпорядників (форми 2д/2м/4-1д/4-2д/7д/9д)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_budget_estimate',
    ],
    'data': [
        'security/ir.access.csv',
        'reports/budget_estimate_report.xml',
        'reports/budget_form_2d_report.xml',
        'reports/budget_multi_form_report.xml',
        'reports/memorial_order_report.xml',
        'wizard/budget_form_2d_wizard_views.xml',
        'wizard/budget_form_2m_4_7_9_wizard_views.xml',
        'wizard/memorial_order_wizard_views.xml',
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
