{
    'name': 'Ukraine - Agreements: Recurring Invoices (OCA contract)',
    'version': '19.0.1.0.0',
    'category': 'Sales/Localization',
    'summary': 'Recurring invoices of an agreement through the OCA contract module',
    'description': """
Ukraine Agreements: Recurring Invoices
======================================

Міст між ``l10n_ua_agreement`` та OCA ``contract``: періодичний (абонентський)
договір OCA створюється з підписаного договору й посилається на нього.
Встановлюється автоматично, якщо в базі є обидва модулі.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_agreement',
        'contract',
    ],
    'data': [
        'views/agreement_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': True,
}
