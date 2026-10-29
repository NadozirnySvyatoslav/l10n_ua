{
    'name': 'Ukraine - EDO: КЕП without a Service',
    'version': '19.0.1.0.1',
    'category': 'Accounting/Localization',
    'summary': 'Документообіг з кваліфікованим електронним підписом без сервісу ЕДО: '
               'підпис у браузері, підпис контрагента на порталі, вхідні поштою',
    'description': """
Ukraine - EDO: КЕП without a Service
====================================

A provider of ``l10n_ua_edo`` next to Вчасно: the same documents, statuses and
bridges (invoices, sale orders, agreements, vendor bills), but the exchange
goes through Odoo itself.

* The company signs with КЕП in the browser (``l10n_ua_sign``: the key and its
  password never reach the server). The «Send to EDO» wizard chooses the way:
  an EDO service or КЕП; the default comes from the card of the counterparty.
* The counterparty gets an e-mail with a link to the portal, where it views
  the document and signs it with its own КЕП, or rejects it. It may also
  answer the e-mail with a .p7s.
* Incoming documents come by e-mail to the alias of the account: the original
  with its .p7s, an archive (.zip, including one of Вчасно) or a signature with
  the data inside (as id.gov.ua makes it). The counterparty is found by the
  ЄДРПОУ of its certificate; the company countersigns and the archive goes back.
* Whose signature it is comes from its certificate (РНОКПП, ЄДРПОУ, name,
  position, CA, serial number, time). The signature itself is checked by the
  IIT library in the browser of an Odoo user («Check Signatures»).
* The archive, as from an EDO service: the original, a .p7s per signature
  (``Pidpys``/``Pechatka`` + code) and ``Kvytantsiia.pdf`` with the list of the
  signatures and how to check them on czo.gov.ua/verify.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['l10n_ua_edo', 'l10n_ua_sign', 'portal', 'mail'],
    'external_dependencies': {'python': ['asn1crypto']},
    'data': [
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'report/kep_receipt.xml',
        'views/edo_account_views.xml',
        'views/edo_document_views.xml',
        'views/portal_templates.xml',
        'wizard/kep_reject_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'l10n_ua_edo_kep/static/src/js/kep_verify_action.js',
        ],
        'web.assets_frontend': [
            'l10n_ua_sign/static/src/js/kep_sign_service.js',
            'l10n_ua_edo_kep/static/src/js/portal_kep_sign.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
