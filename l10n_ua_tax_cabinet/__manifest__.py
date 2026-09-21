{
    'name': 'Ukraine - Tax Cabinet Integration',
    'version': '20.0.2.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Integration with cabinet.tax.gov.ua for document sync',
    'description': """
Ukraine Tax Cabinet Integration
===============================

Integration with cabinet.tax.gov.ua (Electronic Tax Cabinet) providing:

* Sync documents from Tax Cabinet (download existing declarations)
* Sign documents with KEP (electronic signature)
* Submit documents to Tax Cabinet
* Manual document upload (XML, PDF)

Features:
1. Download previous documents from cabinet
2. Prepare and manually upload documents
3. (Future) Automatic submission to tax office

KEP key and password never reach the server: every signature (documents and
the Authorization header of the cabinet API) is computed in the browser by
l10n_ua_sign, the server only relays ready signatures.

Extends l10n_ua.tax.document with cabinet-specific fields and actions.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': ['httpx', 'h2'],  # HTTP/2 support for Tax Cabinet API
    },
    'depends': [
        'l10n_ua_tax',
        'l10n_ua_sign',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'wizard/l10n_ua_tax_cabinet_sync_wizard_views.xml',
        'wizard/l10n_ua_tax_document_wizard_views.xml',
        'views/res_company_views.xml',
        'views/l10n_ua_tax_cabinet_document_views.xml',
        'views/l10n_ua_tax_cabinet_config_views.xml',
        'views/menu_views.xml',
        'views/l10n_ua_tax_request_views.xml',
    ],
    'demo': [],
    'assets': {
        'web.assets_backend': [
            'l10n_ua_tax_cabinet/static/src/css/xml_viewer.css',
            'l10n_ua_tax_cabinet/static/src/js/xml_viewer_field.js',
            'l10n_ua_tax_cabinet/static/src/xml/xml_viewer_field.xml',
            # КЕП-підпис ЄРПН переїхав у модуль l10n_ua_sign (переюзабельний).
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
