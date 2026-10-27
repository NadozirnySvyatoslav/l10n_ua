{
    'name': 'Ukraine - Electronic Document Exchange (EDO)',
    'version': '19.0.1.1.1',
    'category': 'Accounting/Localization',
    'summary': 'Обмін первинними документами через сервіси ЕДО (Вчасно, …): '
               'надсилання на підпис, статуси, вхідні документи',
    'description': """
Ukraine - Electronic Document Exchange (EDO)
============================================

Base of the integrations with Ukrainian electronic document exchange services
(ЕДО: Вчасно, Paperless, …). The service itself is a separate provider module
(``l10n_ua_edo_vchasno``).

* EDO account per company: provider, API token, ЄДРПОУ.
* EDO document: incoming or outgoing, status, number, date, amount,
  counterparty by ЄДРПОУ, the original file and the archive with signatures,
  link to the Odoo record it was sent from.
* ``l10n_ua.edo.mixin``: the button «Надіслати у ЕДО» and the status on any
  document model; a bridge module only tells which report to send.
* Scheduled synchronisation of the statuses and of the incoming documents.

The documents are signed in the service; no key is kept in Odoo.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'l10n_ua_company_base'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/edo_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/edo_account_views.xml',
        'views/edo_document_views.xml',
        'wizard/edo_send_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
}
