{
    'name': 'Ukraine - Medecin НСЗУ Contract',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Договори з НСЗУ, пакети медичних послуг, капітація ПМД',
    'description': """
Ukraine Medecin НСЗУ
====================

Інтеграція з Національною службою здоров'я України (НСЗУ).

* Договір НСЗУ (`l10n_ua.medecin.nszu.contract`) з lifecycle:
  draft → submitted → active → expired / terminated
* Пакети медичних послуг (`l10n_ua.medecin.nszu.package`) — каталог
  ПМП, що замовляє НСЗУ (ПМД-капітація, специфікації, ЕМД, тощо)
* Рядки договору з прив'язкою до пакету і тарифу
* Розрахунок капітації для ПМД (Постанова КМУ № 240 «Про затвердження
  Порядку реалізації державних гарантій медичного обслуговування»):
  тариф на одиницю × кількість декларованих пацієнтів × віковий
  коефіцієнт.
* eHealth-stub для майбутньої інтеграції з ЦК eHealth.

Регуляторна база:
* Закон України № 2168-VIII «Про державні фінансові гарантії медичного
  обслуговування населення»
* Постанова КМУ № 240 від 16.02.2018 — Порядок реалізації гарантій
* Накази НСЗУ про специфікації пакетів медичних послуг
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_base',
        'l10n_ua_medecin_patient',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'data/l10n_ua_medecin_nszu_package_data.xml',
        'views/l10n_ua_medecin_nszu_package_views.xml',
        'views/l10n_ua_medecin_nszu_contract_views.xml',
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
