{
    'name': 'Ukraine - Full Localization',
    'summary': 'Install all Ukrainian localization modules',
    'description': """
Ukraine - Full Localization Package
===================================

This meta-package installs the complete Ukrainian localization for Odoo 20,
including all modules for HR, Payroll, Accounting, Tax Reporting, Banking,
Delivery, Marketplaces, and PRRO (cash registers).

**Included Module Categories:**

HR & Payroll (1C:ЗУП replacement)
---------------------------------
* Employee management with Ukrainian specifics
* Military accounting
* Labor contracts and work schedules
* Salary calculations (PDFO, Military Tax, ESV)
* Vacations, sick leaves, time tracking
* Government reporting (PFU, DPS)

Accounting & Tax
----------------
* Ukrainian chart of accounts
* VAT accounting and reporting
* Fixed assets management
* Tax Cabinet integration
* FOP (sole proprietor) support

Banking
-------
* NBU currency rates sync
* PrivatBank integration
* Monobank integration
* Bank statement import

Delivery
--------
* Nova Poshta integration
* Ukrposhta integration
* Meest Express integration

Marketplaces
------------
* Rozetka Seller API
* Prom.ua API
* Hotline.ua feeds
* Price.ua feeds

PRRO (Cash Registers)
---------------------
* Checkbox integration
    """,
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations',
    'author': 'Many2one',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        # HR & Payroll
        'l10n_ua_hr_base',
        'l10n_ua_hr_contract',
        'l10n_ua_hr_salary',
        'l10n_ua_hr_salary_account',
        'l10n_ua_hr_reports',
        'l10n_ua_hr_documents',
        'l10n_ua_hr_documents_certificates',
        'l10n_ua_hr_holidays',
        'l10n_ua_hr_fss',
        'l10n_ua_hr_attendance_sheet',
        # Accounting & Tax
        'l10n_ua_accounting',
        'l10n_ua_account_vat',
        'l10n_ua_assets',
        'l10n_ua_tax',
        'l10n_ua_tax_cabinet',
        'l10n_ua_tax_F0103309',
        'l10n_ua_fop',
        'l10n_ua_doc_reports',
        # Banking
        'l10n_ua_bank_sync',
        'l10n_ua_bank_privat',
        'l10n_ua_bank_mono',
        'l10n_ua_bank_vst',
        'l10n_ua_bank_payment',
        'l10n_ua_bank_openbanking',
        'l10n_ua_bank_text',
        'l10n_ua_bank_currency_sync',
        # Delivery
        'l10n_ua_delivery_novaposhta',
        'l10n_ua_delivery_ukrposhta',
        'l10n_ua_delivery_meest',
        # Marketplaces
        'l10n_ua_marketplace_rozetka',
        'l10n_ua_marketplace_prom',
        'l10n_ua_marketplace_hotline',
        'l10n_ua_marketplace_priceua',
        # PRRO
        'l10n_ua_prro_checkbox',
        # Other
        'l10n_ua_payment_link',
    ],
    'data': [],
    'installable': True,
    'auto_install': False,
    'application': True,
    'price': 250,
    'currency': 'EUR'
}
