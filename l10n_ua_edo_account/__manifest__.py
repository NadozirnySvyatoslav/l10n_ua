{
    'name': 'Ukraine - EDO for Invoices',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Надсилання рахунків, актів і видаткових у ЕДО; рахунок постачальника з вхідного документа',
    'description': """
Ukraine - EDO for Invoices
==========================

* «Надіслати у ЕДО» on invoices and bills: the Ukrainian forms of
  l10n_ua_doc_reports (Акт, Видаткова накладна, Рахунок-фактура) come first.
* EDO status and documents on the invoice form.
* An incoming EDO document becomes a draft vendor bill with the PDF attached.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_ua_edo'],
    'data': [
        'views/edo_send_action.xml',
        'views/account_move_views.xml',
        'views/edo_document_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'auto_install': True,
}
