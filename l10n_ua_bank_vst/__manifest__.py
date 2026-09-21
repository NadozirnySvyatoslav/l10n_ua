{
    'name': 'Ukraine - VST Bank (iBank 2 UA) Integration',
    'version': '20.0.1.0.0',
    'summary': 'Імпорт виписок VST Bank (Банк Восток) з файлу iBank 2 UA (CSV)',
    'category': 'Accounting/Localizations',
    'author': 'Svyatoslav Nadozirny',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_sync',
    ],
    'data': [
        'security/ir.access.csv',
        'views/l10n_ua_bank_vst_config_views.xml',
    ],
    'installable': True,
    'application': False,
}
