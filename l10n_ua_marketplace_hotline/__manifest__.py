{
    'name': 'Ukrainian Marketplace: Hotline',
    'summary': 'Hotline.ua price comparison feed integration',
    'description': """
Ukrainian Marketplace Integration - Hotline
============================================

This module adds Hotline.ua price comparison portal integration
to the Ukrainian Marketplace module.

Features:
- YML feed generation for Hotline.ua
- Product catalog export in Hotline format
- Category mapping to Hotline categories

Note: Hotline.ua is a feed-only integration (no API for orders/stock sync).
The feed URL can be submitted to Hotline merchant portal.
    """,
    'version': '20.0.1.0.0',
    'category': 'Sales/Sales',
    'author': 'NDEV',
    'website': 'https://ndev.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_marketplace_base',
    ],
    'data': [
        'views/marketplace_backend_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
