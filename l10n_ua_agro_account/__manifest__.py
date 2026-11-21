{
    'name': 'Ukraine - Agro Accounting (P(S)BO 30)',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Agricultural produce at initial recognition (P(S)BO 30), allocation '
               'of indirect costs and crop cost calculation for the season',
    'description': """
Ukraine - Agro Accounting (облік за П(С)БО 30, калькуляція)
===========================================================

Part of the "Agro" industry solution (epic #477, issue #473).

* Initial recognition of the harvest (P(S)BO 30 "Biological assets"):
  every harvest receipt posts the produce to account 27 - at the fair value
  less the costs to sell (Dt 27 / Ct 710) or, when the fair value cannot be
  determined, at the planned cost of the technological card (Dt 27 / Ct 23).
  Fair values per product and date.
* Planned yield of the technological card gives the planned cost of a
  kilogram.
* Season cost calculation: costs on account 23 by planting (work orders),
  indirect costs of 23 without a planting (land rent, payroll,
  depreciation) and, optionally, general production overhead (91) are
  allocated to the plantings in proportion to their direct costs. The
  plantings of the closed season are closed - Dt 940 / Ct 23 (fair value
  method) or Dt 27 / Ct 23 for the difference to the planned cost; the
  plantings of the next season (winter crops sown in autumn) stay on 23 as
  work in progress. Actual cost of a ton and of a hectare by crop.
* The stock value of the harvest equals its valuation on account 27: the
  incoming stock move takes the value of the receipt, the debit goes to the
  stock valuation account of the product category (fallback - the produce
  account of the Agro settings), and the adjustment of the planned cost to
  the actual one revalues the stock as well. The produce must use the AVCO
  or FIFO costing method.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_agro_operations',
        'l10n_ua_agro_harvest',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/agro_fair_value_views.xml',
        'views/agro_tech_card_views.xml',
        'views/harvest_receipt_views.xml',
        'views/cost_calculation_views.xml',
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
