{
    'name': 'Ukraine - Bank Currency Sync',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Sync currency rates from NBU, PrivatBank, Monobank',
    'description': """
Ukraine Bank Currency Synchronization
=====================================

Synchronize currency exchange rates from Ukrainian sources:

* NBU (National Bank of Ukraine) - official rates
* PrivatBank - commercial bank rates
* Monobank - commercial bank rates

Features:
* Manual and scheduled sync
* Multiple rate providers
* Rate history tracking
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'l10n_ua_bank_sync',  # For Bank UA menu integration
    ],
    'data': [
        'security/ir.access.csv',
        'data/res_currency_rate_provider_data.xml',
        'data/ir_cron_data.xml',
        'views/res_currency_rate_provider_views.xml',
        'views/res_currency_views.xml',
        'wizard/currency_sync_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
