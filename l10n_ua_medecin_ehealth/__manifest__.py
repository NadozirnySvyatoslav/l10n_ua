{
    'name': 'Ukraine - Medecin eHealth API',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Інтеграція з ЦК eHealth (МОЗ): декларації, eRx, eReferral',
    'description': """
Medecin eHealth
================

Skeleton-інтеграція з Центральною компонентою eHealth МОЗ України.

* Конфігурація API (base URL, client_id, client_secret) — `ir.config_parameter`
* OAuth2 client_credentials flow (stub)
* Реєстрація декларації пацієнта з лікарем (POST /api/declarations) — stub
* Відправка електронного рецепту (eRx) — stub
* Електронні направлення (ePN) — stub
* Логування запитів у `l10n_ua.ehealth.request.log`

⚠️ Це **каркас**, який реалізує HTTP-шар і структуру моделей. Реальні
endpoints, формати тіл запитів і автентифікація eHealth не публічні —
потрібно отримати:
* URL `api.ehealth.gov.ua` для прод / staging
* Client credentials через звернення до МОЗ
* КЕП (qualified electronic signature) для підпису декларацій

Без цих даних модуль працює тільки в **dry-run / logging** режимі.

Регуляторна база:
* ЗУ № 2168-VIII (НСЗУ) ст. 7-8
* ПКМУ № 411 (Положення про eHealth)
* Наказ МОЗ № 503 (порядок вибору лікаря ПМД)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_patient',
    ],
    'data': [
        'security/ir.access.csv',
        'views/l10n_ua_ehealth_request_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/l10n_ua_medecin_declaration_views.xml',
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
