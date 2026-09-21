{
    'name': 'Ukraine - Bank Payment Orders (КЕП)',
    'version': '20.0.1.0.0',
    'summary': 'Вихідні платіжні доручення з клієнтським КЕП-підписом',
    'category': 'Accounting/Localizations',
    'author': 'Svyatoslav Nadozirny',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
        'l10n_ua_sign',
    ],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/l10n_ua_bank_payment_views.xml',
    ],
    'installable': True,
    'application': False,
}
