{
    'name': 'Ukraine - PRRO Base',
    'version': '20.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian PRRO (fiscal registrar) base module',
    'description': """
Ukraine PRRO Base Module
========================

Base module for Ukrainian PRRO (fiscal registrar) integrations providing:

* PRRO configuration model
* Fiscal receipt model
* Shift management
* Abstract mixin for PRRO providers

Requires l10n_ua_account_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_account_base',
        'l10n_ua_product_base',
        'point_of_sale',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/pos_payment_method_data.xml',
        'views/l10n_ua_prro_config_views.xml',
        'views/l10n_ua_prro_receipt_views.xml',
        'views/l10n_ua_prro_shift_views.xml',
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
