{
    'name': 'Ukraine - PrivatBank Integration',
    'version': '20.0.1.2.0',
    'category': 'Accounting/Localization',
    'summary': 'PrivatBank API + file statement import (XLS/XLSX/CSV/MultiCash)',
    'description': """
Ukraine PrivatBank Integration
==============================

PrivatBank API integration providing:

* Privat24 Business Autoclient API support
* Legacy Merchant API support (for older integrations)
* Automatic bank statement import
* Corporate card support

Extends l10n_ua_bank_sync with PrivatBank-specific functionality.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'external_dependencies': {
        'python': ['xlrd', 'openpyxl'],
    },
    'data': [
        'views/l10n_ua_bank_privat_config_views.xml',
    ],
    'demo': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
