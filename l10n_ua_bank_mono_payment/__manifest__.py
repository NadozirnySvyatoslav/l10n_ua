{
    'name': 'Ukraine - monobank Payments (Corporate API)',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Send payment orders to monobank for signing in the app',
    'description': """
Payment orders through the monobank Corporate API
=================================================

* A second way to send an outgoing payment order (``l10n_ua.bank.payment``)
  besides the file signed with a qualified signature: each payment is
  prepared in monobank (``/ext/v1/payment/prepare``) and signed by the
  director in the monobank app or web cabinet, so no signature in Odoo
  is needed.
* Budget payments: payment code, additional information and the actual
  payer.
* Payment state from the bank (awaiting signature, declined, in the
  statement), refreshed by a scheduled action; an executed payment is
  linked to its bank statement line by its external reference.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_bank_mono',
        'l10n_ua_bank_payment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/l10n_ua_bank_payment_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': True,
    'price': 0,
    'currency': 'EUR',
}
