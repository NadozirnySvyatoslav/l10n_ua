{
    'name': 'Ukraine - Nova Poshta Delivery',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Nova Poshta delivery integration',
    'description': """
Ukraine Nova Poshta Delivery
============================

Nova Poshta API integration providing:

* TTN (express waybill) creation
* Label printing
* Tracking
* Cost calculation
* Warehouse directory sync
* COD (cash on delivery) support
* Return delivery

Requires l10n_ua_delivery_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_delivery_base',
    ],
    'data': [
        'views/delivery_carrier_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
