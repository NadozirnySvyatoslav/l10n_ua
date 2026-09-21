{
    'name': 'Ukraine - Ukrposhta Delivery',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Ukrposhta delivery integration',
    'description': """
Ukraine Ukrposhta Delivery
==========================

Ukrposhta API integration providing:

* Waybill creation
* Label printing
* Tracking
* Branch directory sync

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
