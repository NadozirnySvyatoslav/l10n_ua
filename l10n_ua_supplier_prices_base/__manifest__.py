{
    'name': 'Ukraine - Supplier Prices Base',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'Базовий модуль для імпорту прайс-листів постачальників',
    'description': """
Базовий модуль для імпорту цін постачальників.

Можливості:
- Конфігурація джерел (manual upload базово; розширюється на API/SFTP/email)
- Налаштовуваний mapping (розширюється парсерами JSON/XML/CSV/XLSX)
- State machine для покрокової обробки (fetch → parse → apply)
- Історія імпортів зі збереженням raw файлу для повторного парсингу
- Multi-currency, опціональна прив'язка до компанії
- Налаштовувані timeouts і watchdog для застряглих імпортів

Розширення:
- l10n_ua_supplier_prices_api      — fetcher через HTTP API
- l10n_ua_supplier_prices_sftp     — fetcher через SFTP
- l10n_ua_supplier_prices_email    — fetcher через IMAP/email
- l10n_ua_supplier_prices_xml      — XML parser
- l10n_ua_supplier_prices_xlsx     — Excel parser
- l10n_ua_supplier_prices_csv      — CSV parser
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'product',
        'purchase',
        'mail',
        'l10n_ua_account_base',
    ],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/ir_cron_data.xml',
        'data/ir_sequence_data.xml',
        'views/l10n_ua_supplier_price_mapping_views.xml',
        'views/l10n_ua_supplier_price_source_views.xml',
        'views/l10n_ua_supplier_price_import_views.xml',
        'views/menu.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
