{
    'name': 'Ukraine - Open Banking (PSD2)',
    'version': '20.0.1.0.0',
    'summary': 'Open Banking (Berlin Group NextGenPSD2) провайдер: виписки, згоди, платежі',
    'category': 'Accounting/Localizations',
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'data': [
        'views/l10n_ua_bank_openbanking_config_views.xml',
    ],
    'installable': True,
    'application': False,
}
