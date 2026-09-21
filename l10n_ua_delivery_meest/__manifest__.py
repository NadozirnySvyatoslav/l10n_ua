{
    'name': 'Ukraine - Meest Delivery',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Meest delivery integration',
    'description': """
Ukraine Meest Delivery
======================

Meest API integration providing:

* Waybill creation
* Label printing
* Tracking
* Warehouse directory sync

Requires l10n_ua_delivery_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_delivery_base',
    ],
    'data': [],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
