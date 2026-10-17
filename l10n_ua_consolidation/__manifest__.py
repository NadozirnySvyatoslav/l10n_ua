{
    'name': 'Ukraine - Consolidated Financial Statements (1-к, 2-к)',
    'version': '19.0.1.0.3',
    'category': 'Accounting/Localization',
    'summary': 'Консолідований баланс (ф. 1-к) і звіт про фінансові результати (ф. 2-к) '
               'групи компаній за НП(С)БО 2',
    'description': """
Ukraine - Consolidated Financial Statements
===========================================

Consolidated statements of a group of companies kept in one Odoo database
(НП(С)БО 2 «Консолідована фінансова звітність», наказ Мінфіну № 628 від
27.06.2013; forms № 1-к and № 2-к — додатки до НП(С)БО 1, наказ № 73):

* Group: parent company, subsidiaries with ownership %, acquisition date and
  the parent's investment (from account 14 or manual).
* Line-by-line summation of Form 1 / Form 2 rows of ``l10n_ua_accounting``
  per company.
* Eliminations: intra-group receivables/payables/loans and intra-group income
  and expenses (journal items against group partners), intra-group sales
  against cost of sales, the parent's investment against the subsidiary's
  equity at acquisition (goodwill on consolidation, row 1055), non-controlling
  interest (rows 1490, 2470/2475).
* Manual adjustment lines with explanation (unrealised profit in inventory,
  fair value adjustments, reclassifications).
* Worksheet (pivot rows × companies / eliminations), printable 1-к and 2-к.
* The user must have access to every company of the group.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_accounting',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/consolidation_security.xml',
        'views/consolidation_group_views.xml',
        'views/consolidation_report_views.xml',
        'views/menu_views.xml',
        'report/consolidation_report.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
