{
    'name': 'Ukraine - Bank Sync Base',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian bank synchronization base module',
    'description': """
Ukraine Bank Sync Base Module
=============================

Base module for Ukrainian bank integrations providing:

* Bank extensions (MFO code)
* Partner bank account extensions (IBAN validation)
* Bank sync configuration model
* Sync job model with state management
* Import logging with stored raw payload
* Reprocess capability without re-fetching
* Wizard for custom date range sync
* Bank statement import base

Provider modules (l10n_ua_bank_privat, l10n_ua_bank_mono) inherit
from this module and implement bank-specific API calls.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_account_base',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'data/res_bank_data.xml',
        'data/ir_cron_data.xml',
        'wizard/l10n_ua_bank_sync_wizard_views.xml',
        'views/res_bank_views.xml',
        'views/res_partner_bank_views.xml',
        'views/l10n_ua_bank_sync_config_views.xml',
        'views/l10n_ua_bank_sync_job_views.xml',
        'views/account_bank_statement_views.xml',
        'views/account_journal_views.xml',
        'views/menu_views.xml',
        'wizard/l10n_ua_bank_statement_import_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
