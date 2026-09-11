{
    'name': 'Ukraine - PUMB Integration',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'PUMB Open Banking API (NextGenPSD2): consents and bank statements',
    'description': """
Ukraine PUMB Integration
========================

PUMB Open Banking API (Berlin Group NextGenPSD2) integration providing:

* mTLS connection with an open banking certificate (QWAC)
* Account access consent: creation, confirmation in PUMB Online
  (SCA DECOUPLED), status refresh and revocation
* Automatic bank statement import (booked transactions, paginated)
* Sandbox and production environments

Extends l10n_ua_bank_sync with PUMB-specific functionality.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'external_dependencies': {
        'python': ['cryptography'],
    },
    'data': [
        'views/l10n_ua_bank_pumb_config_views.xml',
    ],
    'demo': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
