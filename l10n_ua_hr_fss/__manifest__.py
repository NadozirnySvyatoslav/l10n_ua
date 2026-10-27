{
    'name': 'Ukraine - HR PFU Sick-Leave Settlements',
    'version': '19.0.1.1.0',
    'summary': 'Взаєморозрахунки з ПФУ (Пенсійний фонд України): звірка, сальдо, відшкодування лікарняних',
    'category': 'Human Resources/Payroll',
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_holidays',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/hr_fss_settlement_views.xml',
    ],
    'installable': True,
    'application': False,
}
