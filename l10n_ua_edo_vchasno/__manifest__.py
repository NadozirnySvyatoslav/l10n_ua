{
    'name': 'Ukraine - EDO: Вчасно',
    'version': '19.0.1.2.1',
    'category': 'Accounting/Localization',
    'summary': 'Провайдер ЕДО «Вчасно»: завантаження документів на підпис, статуси, вхідні',
    'description': """
Ukraine - EDO: Вчасно
=====================

Connects ``l10n_ua_edo`` to Вчасно.ЕДО (API v2, token in the header
``Authorization``):

* upload a PDF with the recipient (ЄДРПОУ, e-mails), number, date, amount;
* send it to the recipient when the recipient signs first;
* statuses 7000–7010 mapped onto the EDO states;
* incoming documents, the original and the archive with signatures.

The documents are signed in Вчасно; no key is kept in Odoo. The address of
the API is the system parameter ``l10n_ua_edo_vchasno.base_url``
(default https://edo.vchasno.ua/api/v2).
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['l10n_ua_edo'],
    'external_dependencies': {'python': ['requests']},
    'data': [],
    'images': ['static/description/banner.png'],
    'installable': True,
    'auto_install': False,
}
