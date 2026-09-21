{
    'name': 'Ukraine - Prom.ua Marketplace',
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Prom.ua marketplace integration',
    'description': """
Ukraine Prom.ua Marketplace
===========================

Prom.ua marketplace integration providing:

* API authentication with Bearer token
* Order import from Prom.ua API
* Order status synchronization
* Product import from Prom.ua catalog
* Stock synchronization via API
* Price synchronization via API
* Webhook support for real-time notifications

API Documentation: https://public-api.docs.prom.ua/

Requires l10n_ua_marketplace_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_marketplace_base',
    ],
    'data': [
        'views/prom_backend_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'demo': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
