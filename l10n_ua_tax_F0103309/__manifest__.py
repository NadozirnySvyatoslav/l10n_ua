{
    'name': 'Ukraine - Single Tax Declaration (F0103309)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Single Tax Declaration form F0103309 for FOP',
    'description': """
Ukraine Single Tax Declaration (F0103309)
==========================================

This module adds support for creating Single Tax Declaration (Декларація
платника єдиного податку) form F0103309 version 9.

Features:
* Wizard for filling declaration data
* XML generation in DPS format (windows-1251 encoding)
* Support for FOP groups 1, 2, 3
* Activity codes (KVED) management
* Income and tax calculation

Requires l10n_ua_tax_cabinet module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.access.csv',
        'wizard/l10n_ua_tax_F0103309_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': True,
}
