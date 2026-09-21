{
    'name': 'Ukraine - Rozetka Marketplace',
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Rozetka marketplace integration',
    'description': """
Ukraine Rozetka Marketplace
===========================

Rozetka marketplace integration providing:

* API authentication with Bearer token
* Order import from Rozetka Seller API
* Order status synchronization
* Stock synchronization via API
* Price synchronization via API
* Webhook support for real-time order notifications
* Category mapping

API Documentation: https://api-seller.rozetka.com.ua/apidoc/

Requires l10n_ua_marketplace_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_marketplace_base',
    ],
    'data': [
        'views/rozetka_backend_views.xml',
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
