{
    'name': 'Ukraine - NovaPay Integration',
    'version': '19.0.1.0.1',
    'category': 'Accounting/Localization',
    'summary': 'NovaPay Business API integration for bank statements',
    'description': """
Ukraine NovaPay Integration
===========================

NovaPay Business cabinet API (business.novapay.ua) integration providing:

* JWT authorization with a rotating refresh token
* Automatic account lookup by the IBAN of the bank journal
* Automatic bank statement import (account extract) with counterparties
* Opening and closing balances from account turnovers

Extends l10n_ua_bank_sync with NovaPay-specific functionality.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/l10n_ua_bank_novapay_config_views.xml',
    ],
    'demo': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
