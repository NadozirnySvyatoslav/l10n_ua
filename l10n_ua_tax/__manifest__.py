{
    'name': 'Ukraine - Tax',
    'version': '20.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian tax documents and reporting',
    'description': """
Ukraine Tax Module
==================

Ukrainian tax accounting base module providing:

* Tax documents (declarations, reports, etc.)
* Document types (F0103309, VAT, ESV, etc.)
* Tax periods (month, quarter, year)
* Budget classification codes (КБК)
* Minimum wage by date (base for minimum ESV and single tax income limits)
* Base taxes: PDFO 18%, Military tax 5%, ESV 22%, VAT 20%/7%/0%

Workflow:
1. Create tax document
2. Fill data via wizard
3. Generate XML
4. Submit to tax office (via l10n_ua_tax_cabinet)

Requires l10n_ua_account_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'l10n_ua_account_base',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/account_tax_data.xml',
        'data/l10n_ua_budget_code_data.xml',
        'data/l10n_ua_min_wage_data.xml',
        'data/l10n_ua_tax_document_type_data.xml',
        'views/account_tax_views.xml',
        'views/l10n_ua_tax_period_views.xml',
        'views/l10n_ua_tax_document_type_views.xml',
        'views/l10n_ua_tax_document_views.xml',
        'views/l10n_ua_budget_code_views.xml',
        'views/res_company_views.xml',
        'views/menu_views.xml',
        'views/l10n_ua_min_wage_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
