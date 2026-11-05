{
    'name': 'Ukraine - Commercial Budgeting',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Income & expense (БДР) and cash flow (БДДС) budgets with plan vs actual '
               'for Odoo Community',
    'description': """
Commercial Budgeting for Ukraine
================================

Budgeting for commercial companies on Odoo Community (the standard
``account_budget`` is Enterprise-only). Public-sector estimates (кошториси)
are covered by the ``l10n_ua_budget_*`` modules; this module does not depend
on them.

* Budget items (статті бюджету) mapped to accounts and/or account code
  prefixes, optionally restricted by analytic accounts; hierarchical
* Income & Expense Budget (БДР, accrual): actuals from posted journal items
* Cash Flow Budget (БДДС, cash basis): actuals from cash and bank movements
  classified by the counterpart account, as the direct method of Form 3
* Budgets by month / quarter / year, scenarios (base / optimistic /
  pessimistic), hierarchy company → responsibility centre (ЦФВ) → project
  through parent budgets and analytic accounts
* Draft → Approved → Closed workflow, planned figures locked after approval
* Actuals, deviation, remaining and execution %, pivot and graph analysis
* Copy a budget to another scenario or period with a coefficient
* Excel export / import of the plan as an items × periods matrix
* Optional budget control on vendor bills (warning or block), off by default
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'analytic',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/budget_data.xml',
        'wizard/budget_wizard_views.xml',
        'views/budget_item_views.xml',
        'views/budget_line_views.xml',
        'views/budget_plan_views.xml',
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
