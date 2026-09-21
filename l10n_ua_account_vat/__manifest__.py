{
    'name': 'Ukraine - Account VAT',
    'version': '20.0.5.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian VAT: tax invoices, registers, declaration',
    'description': """
Ukraine VAT Module
==================

Ukrainian VAT accounting providing:

* Tax invoice (Податкова накладна) — issued and received
* Adjustment calculation (Розрахунок коригування)
* VAT register — auto-populate from tax invoices
* VAT declaration — auto-calculate from registers
* XML export for ERPN registration
* XLSX export for registers and declaration
* Auto-create PN from account.move invoices

Requires l10n_ua_tax module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua_product_base',
        'l10n_ua_tax',
        'l10n_ua_sign',
        'l10n_ua_tax_cabinet',
    ],
    'data': [
        'security/ir.access.csv',
        'security/l10n_ua_account_vat_security.xml',
        'data/ir_sequence_data.xml',
        'report/tax_invoice_report.xml',
        'views/res_company_views.xml',
        'views/res_partner_views.xml',
        'views/l10n_ua_tax_invoice_views.xml',
        'views/l10n_ua_vat_register_views.xml',
        'views/l10n_ua_vat_declaration_views.xml',
        'views/l10n_ua_vat_erpn_limit_views.xml',
        'views/account_move_views.xml',
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
