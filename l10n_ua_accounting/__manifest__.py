{
    'name': 'Ukraine - Accounting Suite',
    'version': '19.0.7.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian accounting: PKO/VKO, Cash Book, Balance Sheet, P&L, Cash Flow',
    'description': """
Ukraine Accounting Suite
========================

Complete Ukrainian accounting functionality for Odoo:

**Cash Operations (ПКО/ВКО):**
* Cash Receipt Orders (Прибуткові касові ордери, форма КО-1)
* Cash Disbursement Orders (Видаткові касові ордери, форма КО-2)
* Automatic numbering sequences per cash journal
* Ukrainian printed forms

**Cash Book (Касова книга):**
* Daily cash movements report
* Opening/closing balances
* Automatic calculations from posted payments
* Printable format

**Reconciliation Acts (Акти звірки):**
* Partner balance reconciliation
* Receivable/Payable filtering
* Opening/closing balances
* Printable format for signing

**Financial Statements:**
* Balance Sheet (Баланс, Форма №1)
* Profit & Loss Statement (Звіт про фінансові результати, Форма №2)
* Cash Flow Statement, direct method (Звіт про рух грошових коштів, Форма №3)
* Automatic calculation from Chart of Accounts
* Comparison with previous period
* PDF export

**Menu "Бухгалтерія UA":**
* Root menu with sequence 51
* Documents, Cash, Reports, Settings sections
* Links to OSV, Journal Orders from l10n_ua_account_base

Dependencies:
* l10n_ua_account_base - Base localization (directories, validators)
* l10n_ua_tax - Tax management
* l10n_ua_bank_sync - Bank synchronization
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'analytic',
        'mail',
        'hr',
        'product',
        'uom',
        'stock',
        'l10n_ua_account_base',
        'l10n_ua_doc_reports',
        'l10n_ua_tax',
        'l10n_ua_tax_cabinet',
        'l10n_ua_bank_sync',
        'l10n_ua_assets',
        'l10n_ua_bank_currency_sync',
        'l10n_ua_account_vat',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        # Data
        'data/period_closing_data.xml',
        'data/cash_limit_cron.xml',
        'data/currency_exchange_data.xml',
        'data/account_menu_data.xml',
        # Views
        'views/res_company_views.xml',
        'views/account_payment_views.xml',
        'views/account_journal_views.xml',
        'views/service_act_views.xml',
        'views/advance_report_views.xml',
        'views/l10n_ua_balance_report_views.xml',
        'views/l10n_ua_pnl_report_views.xml',
        'views/l10n_ua_cashflow_report_views.xml',
        'views/l10n_ua_period_closing_views.xml',
        'views/l10n_ua_currency_revaluation_views.xml',
        'views/l10n_ua_currency_exchange_views.xml',
        'views/l10n_ua_aging_report_views.xml',
        # Wizards
        'wizard/cash_book_wizard_views.xml',
        'wizard/reconciliation_act_wizard_views.xml',
        'wizard/payment_order_wizard_views.xml',
        'wizard/inventory_act_wizard_views.xml',
        # Menu
        'views/menu_views.xml',
        # Reports
        'report/report_templates.xml',
        'report/pko_report.xml',
        'report/vko_report.xml',
        'report/cash_book_report.xml',
        'report/reconciliation_act_report.xml',
        'report/balance_sheet_report.xml',
        'report/pnl_report.xml',
        'report/cashflow_report.xml',
        'report/service_act_report.xml',
        'report/advance_report_report.xml',
        'report/payment_order_report.xml',
        'report/inventory_act_report.xml',
        # invoice_report_inherit.xml moved to l10n_ua_doc_reports
    ],
    'demo': [],
    'images': ['static/description/banner.png'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
