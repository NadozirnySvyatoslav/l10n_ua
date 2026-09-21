{
    'name': 'Ukraine - Budget Treasury DBF Import',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Імпорт виписок ДКСУ у форматі DBase III/IV',
    'description': """
Ukraine Budget Treasury DBF Import
==================================

Плагін до `l10n_ua_budget_treasury`, що додає підтримку реальних виписок
ДКСУ у форматі DBase III/IV — це найпоширеніший формат, який експортує
автоматизована система Казначейства.

* Чистий Python-парсер DBF (без зовнішніх залежностей)
* Підтримує очікувані поля Казначейства: DOC_NUM, DOC_DATE, MFO_KOR,
  KOD_KOR, NAZ_KOR, DT, KT, SUM_, NAZ_PRIZ
* Кодування CP866 (стандарт для DBase III) з fallback на UTF-8
* Hooks для адаптації під конкретний клієнтський формат:
  переозначити `_dbf_field_map()` у дочірньому модулі

⚠️ Конкретні назви полів варіюються між версіями ПЗ Казначейства. Перед
використанням у проді треба звірити з реальним sample-файлом і за
потреби переозначити маппінг.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_budget_treasury',
    ],
    'data': [],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
