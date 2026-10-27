{
    'name': 'Ukraine - EDO for Agreements',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Підписання договорів через ЕДО: договір стає підписаним, архів із підписами — у договорі',
    'description': """
Ukraine - EDO for Agreements
============================

* «Надіслати у ЕДО» on an agreement: the printed agreement comes first.
* Sent for signature → the agreement is «To Sign»; signed by all parties →
  «Signed», with the signature date and the archive with the signatures as
  the signed document.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['l10n_ua_agreement', 'l10n_ua_edo'],
    'data': [
        'views/edo_send_action.xml',
        'views/agreement_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'auto_install': True,
}
