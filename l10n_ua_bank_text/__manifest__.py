{
    'name': 'Ukraine - Generic Text Bank Statement (BUH-1 / ІБІС)',
    'version': '20.0.1.0.0',
    'summary': 'Конфігурований імпорт текстової виписки клієнт-банку (BUH-1, ІБІС, CSV)',
    'category': 'Accounting/Localizations',
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'data': [
        'views/l10n_ua_bank_text_config_views.xml',
    ],
    'installable': True,
    'application': False,
}
