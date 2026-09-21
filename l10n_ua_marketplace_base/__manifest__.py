{
    'name': 'Ukraine - Marketplace Base',
    'version': '20.0.1.1.0',
    'category': 'Sales/Sales',
    'summary': 'Ukrainian marketplace integrations base module',
    'description': """
Ukraine Marketplace Base Module
===============================

Base module for Ukrainian marketplace integrations providing:

* Marketplace backend configuration
* Product pricelist management
* YML/XML feed generation
* Order import with partner matching
* Webhook and API endpoints
* Cron jobs for automated synchronization

Supported marketplaces (via specific modules):
* Rozetka
* Prom.ua
* Epicentr
* Allo
* Hotline (price feed only)
* Price.ua (price feed only)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'stock',
        'delivery',
        'account',
        'phone_validation',
        'l10n_ua_product_base',
    ],
    'data': [
        # Security
        'security/l10n_ua_marketplace_security.xml',
        'security/ir.access.csv',
        # Data
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        # Views
        'views/marketplace_backend_views.xml',
        'views/marketplace_order_views.xml',
        'views/marketplace_pricelist_views.xml',
        'views/marketplace_category_views.xml',
        'views/marketplace_status_mapping_views.xml',
        'views/product_template_views.xml',
        'views/menu_views.xml',
        # Wizards
        'wizard/marketplace_order_cancel_wizard.xml',
    ],
    'demo': [
        'demo/marketplace_demo.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
