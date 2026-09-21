{
    'name': 'Ukraine - monobank Integration',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'monobank API integration for bank statements',
    'description': """
Ukraine monobank Integration
============================

monobank API integration providing:

* monobank API connection
* Automatic bank statement import for FOP
* Webhook support for real-time updates
* Multiple accounts support

Extends l10n_ua_bank_sync with monobank-specific functionality.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'data': [
        'views/l10n_ua_bank_mono_config_views.xml',
    ],
    'demo': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
