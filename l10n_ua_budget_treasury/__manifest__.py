{
    'name': 'Ukraine - Budget Treasury (Казначейство)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Інтеграція з Державною казначейською службою: реєстраційні рахунки, контроль ліміту, виписки',
    'description': """
Ukraine Budget Treasury
=======================

Розширює бюджетний облік інтеграцією з Державною казначейською службою (ДКСУ).

* Довідник територіальних органів ДКСУ (центральний апарат + обласні
  ГУДКСУ + Київ та Севастополь)
* Розширення `account.journal` — позначка казначейського рахунку,
  тип (реєстраційний / спеціальний реєстраційний / поточний), прив'язка
  до територіального органу, КПКВК, фонду
* Контроль ліміту асигнувань: перед проведенням платежу перевіряє,
  що у відповідному рядку затвердженого кошторису достатньо залишку
  (план мінус касове виконання). Кидає UserError якщо ні.
* Wizard імпорту виписки з ДКСУ (поки що з CSV-плейсхолдером —
  конкретний формат буде підключатися окремо для кожного клієнта)

Регуляторна база:
* Бюджетний кодекс України ст. 43, 48 (єдиний казначейський рахунок)
* Наказ Мінфіну № 938 від 28.10.2015 — порядок казначейського обслуговування
* Наказ Мінфіну № 130 від 17.03.2017 — порядок обслуговування доходів
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_budget_base',
        'l10n_ua_budget_estimate',
    ],
    'data': [
        'security/ir.access.csv',
        'data/l10n_ua.treasury.organ.csv',
        'views/l10n_ua_treasury_organ_views.xml',
        'views/account_journal_views.xml',
        'wizard/l10n_ua_treasury_statement_import_views.xml',
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
