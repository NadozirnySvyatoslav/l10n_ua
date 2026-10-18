{
    'name': 'Ukraine - Sale Documents in E-mails',
    'version': '19.0.1.0.1',
    'category': 'Accounting/Localization',
    'summary': 'Рахунок-фактура в листах замовлень, акт / видаткова накладна в листах рахунків, '
               'автоматичний рахунок після онлайн-оплати',
    'description': """
Ukraine - Sale Documents in E-mails
===================================

Closes the document flow of a web shop: order → payment → posted customer
invoice → primary document (акт / видаткова накладна), with the Ukrainian forms
of ``l10n_ua_doc_reports``.

* Order e-mails (quotation, order confirmation, payment executed) attach the
  **Рахунок-фактура** instead of the standard order PDF (per company).
* Invoice e-mails attach the primary document next to the Odoo invoice PDF:
  **Акт виконаних робіт**, **Видаткова накладна** or chosen per invoice
  (services → акт, goods → видаткова накладна, mixed → both).
* Automatic invoicing after online payment exposed in the same settings block.
* Transactions of payment providers in **test** mode never create invoices.

Mail templates of Odoo are not modified.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'sale',
        'l10n_ua_doc_reports',
    ],
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
