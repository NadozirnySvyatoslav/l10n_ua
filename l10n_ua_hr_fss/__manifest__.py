{
    'name': 'Ukraine - HR FSS Settlements',
    'version': '20.0.1.0.0',
    'summary': 'Взаєморозрахунки з ФСС: звірка, сальдо, відшкодування лікарняних',
    'category': 'Human Resources/Payroll',
    'author': 'Svyatoslav Nadozirny',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_holidays',
        'account',
    ],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'views/hr_fss_settlement_views.xml',
    ],
    'installable': True,
    'application': False,
}
