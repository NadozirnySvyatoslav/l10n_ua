{
    'name': 'Ukraine - Delivery Base',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Ukrainian delivery carriers base module',
    'description': """
Ukraine Delivery Base Module
============================

Base module for Ukrainian delivery carrier integrations providing:

* Carrier extensions (ua_carrier_type, API settings)
* Abstract mixin for delivery providers
* Common warehouse/branch model
* Shipment tracking base

Requires l10n_ua_account_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'delivery',
        'l10n_ua_account_base',
    ],
    'data': [
        'security/ir.access.csv',
        'views/delivery_carrier_views.xml',
        'views/l10n_ua_delivery_warehouse_views.xml',
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
