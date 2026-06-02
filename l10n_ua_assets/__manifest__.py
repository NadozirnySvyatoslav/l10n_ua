{
    'name': 'Ukraine - Fixed Assets',
    'version': '19.0.3.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian fixed assets: depreciation, OZ-6, acts, MNMA, revaluation, modernization',
    'description': """
Ukraine Fixed Assets Module
===========================

Ukrainian fixed assets localization providing:

* Fixed asset groups (1-16 according to Tax Code)
* Depreciation methods (straight-line, declining balance, production, cumulative)
* Ukrainian depreciation computation with liquidation value
* Inventory card OZ-6 (PDF print)
* Commissioning act (Акт введення в експлуатацію)
* Write-off act (Акт на списання ОЗ)
* Asset revaluation (Переоцінка ОЗ) per П(С)БО 7 with automatic journal entries
* Asset modernization / reconstruction (Модернізація ОЗ) per П(С)БО 7 п.14
  with automatic journal entries and optional useful-life extension
* MNMA (low-value non-current tangible assets) with 50/50 or 100% write-off
* MNMA commissioning and write-off acts

Requires l10n_ua_account_base and l10n_ua_doc_reports modules.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'hr',
        'l10n_ua_account_base',
        'l10n_ua_doc_reports',
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',
        # Data
        'data/l10n_ua_asset_group_data.xml',
        'data/ir_sequence_data.xml',
        # Views
        'views/account_asset_views.xml',
        'views/l10n_ua_asset_modernization_views.xml',
        'views/l10n_ua_asset_revaluation_views.xml',
        'views/l10n_ua_mnma_views.xml',
        'views/menu_views.xml',
        # Reports
        'report/asset_oz6_report.xml',
        'report/asset_commission_report.xml',
        'report/asset_writeoff_report.xml',
        'report/asset_modernization_report.xml',
        'report/asset_revaluation_report.xml',
        'report/mnma_commission_report.xml',
        'report/mnma_writeoff_report.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
