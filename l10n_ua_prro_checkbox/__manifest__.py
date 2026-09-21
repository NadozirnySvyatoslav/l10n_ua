{
    'name': 'Ukraine - PRRO Checkbox',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Checkbox PRRO integration',
    'description': """
Ukraine PRRO Checkbox Integration
=================================

Checkbox PRRO integration providing:

* Checkbox API connection
* Receipt registration
* Shift management (open/close)
* X-report, Z-report
* Service cash input/output
* Return receipts

Requires l10n_ua_prro_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_prro_base',
    ],
    'data': [
        'security/ir.access.csv',
        'views/l10n_ua_prro_checkbox_config_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
