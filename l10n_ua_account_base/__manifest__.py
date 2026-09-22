{
    'name': 'Ukraine - Account Base Localization',
    'version': '20.0.1.3.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian localization base module with accounting',
    'description': """
Ukraine Base Localization Module
================================

Foundation module for all Ukrainian localization modules providing:

* Partner extensions (EDRPOU, IPN/RNOKPP validation)
* KOATUU/KATOTTG directory (19000+ records)
* KVED-2010 classifier (1500+ records)
* Tax offices (ДПІ) directory
* Ukrainian address format mixin
* Document formatting mixin (dates, amounts in Ukrainian)
* Validators (EDRPOU, IPN, IBAN)
* Formatters (dates, money, numbers to words)

Accounting features:
* Chart of accounts according to P(S)BO (classes 0-9)
* Account extensions (ua_class, ua_subaccount, analytics_type)
* Document extensions (ua_doc_type, ua_doc_number)
* Journal orders (Журнали-ордери №1-7)
* Trial balance / OSV (Оборотно-сальдова відомість)

This module is required for all other l10n_ua_* modules.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ua',
        'l10n_ua_company_base',
        'l10n_ua_product_base',
    ],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/res_country_state_data.xml',
        'data/l10n_ua_koatuu_data.xml',
        'data/l10n_ua_kved_data.xml',
        'data/l10n_ua_tax_office_data.xml',
        'data/l10n_ua_legal_form_data.xml',
        'data/l10n_ua_bank_data.xml',
        'data/account_chart_template_data.xml',
        'data/l10n_ua_subconto_data.xml',
        'views/res_partner_views.xml',
        'views/res_partner_bank_views.xml',
        'views/l10n_ua_bank_views.xml',
        'views/l10n_ua_koatuu_views.xml',
        'views/l10n_ua_kved_views.xml',
        'views/l10n_ua_tax_office_views.xml',
        'views/account_account_views.xml',
        'views/account_move_views.xml',
        'views/l10n_ua_journal_order_views.xml',
        'views/l10n_ua_osv_views.xml',
        'views/l10n_ua_account_card_views.xml',
        'views/l10n_ua_account_analysis_views.xml',
        'views/l10n_ua_general_ledger_views.xml',
        'views/l10n_ua_chess_sheet_views.xml',
        'views/l10n_ua_subconto_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
