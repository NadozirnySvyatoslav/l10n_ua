{
    'name': 'Ukraine - Import (Foreign Trade)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Import customs declaration IM-40: customs duty, excise and fees in the inventory '
               'cost (landed costs), import VAT as a tax credit document',
    'description': """
Ukraine - Import (зовнішньоекономічні закупівлі)
================================================

Issue #201: the import part of the foreign trade accounting. The export part
(foreign trade contracts, ЕК-10, currency control) lives in l10n_ua_export.

* Import customs declaration (ІМ-40): number, clearance date, customs office,
  foreign trade contract, vendor bills and receipts, invoice value in the
  contract currency, customs value in UAH at the NBU rate of the clearance
  date, customs duty, excise tax, customs fees, import VAT
  (rate × (customs value + duty + excise), Tax Code p. 190.1).
* Customs duty, excise and fees go into the cost of the imported goods
  through the standard Odoo landed costs (stock_landed_costs):
  Dt 281 (stock valuation) - Ct 377 (customs, prepaid customs payments).
* Import VAT: Dt 6441 (tax credit) - Ct 377. The customs declaration is the
  basis for the tax credit (Tax Code p. 201.12, the date - the payment of
  the tax, p. 198.2 / 187.8): a received tax document flagged "import" is
  created, so the declaration shows up in the register of received
  documents and in row 11.1 (11.2, 11.3) of the VAT return, and is left
  out of the appendix D1.
* The ERPN registration limit takes the import VAT of the registers into
  ΣМитноПДВ instead of ΣОтримПДВ.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'stock_landed_costs',
        'l10n_ua_export',
        'l10n_ua_account_vat',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/product_data.xml',
        'views/import_declaration_views.xml',
        'views/account_move_views.xml',
        'views/stock_landed_cost_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
