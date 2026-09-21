{
    'name': 'Ukraine - Education ЄДЕБО Integration',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Education',
    'summary': 'Імпорт/експорт контингенту з ЄДЕБО (Єдина державна електронна база освіти)',
    'description': """
Ukraine Education ЄДЕБО Integration
====================================

Каркас інтеграції з Єдиною державною електронною базою освіти (ЄДЕБО).

* Wizard імпорту списку студентів/учнів з CSV/XLSX (плейсхолдер для
  реального формату ЄДЕБО — підключається окремим плагіном)
* Wizard експорту контингенту в форматі CSV (для подальшого
  завантаження в ЄДЕБО)
* Точка розширення `_parse_custom()` для конкретних форматів файлів
  обміну (XML за специфікацією МОН)

⚠️ ЄДЕБО має закриту специфікацію форматів обміну, яка регулярно
оновлюється. Цей модуль надає інфраструктуру — конкретні формати
рекомендується підключати окремими плагінами для кожного клієнта.

Нормативна база:
* Постанова КМУ № 1098 — Положення про ЄДЕБО
* Наказ МОН про порядок надання даних до ЄДЕБО (актуальну редакцію
  звіряти на mon.gov.ua)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_education_base',
    ],
    'data': [
        'security/ir.access.csv',
        'wizard/l10n_ua_edebo_import_views.xml',
        'wizard/l10n_ua_edebo_export_views.xml',
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
