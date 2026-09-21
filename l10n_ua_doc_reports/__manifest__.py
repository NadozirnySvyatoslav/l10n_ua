{
    'name': 'Ukraine - Accounting Document Reports',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Ukrainian commercial documents: Рахунок-фактура, Видаткова накладна, Акт',
    'description': """
Ukraine - Accounting Document Reports
======================================

QWeb PDF report templates for Ukrainian commercial documents:

* **Рахунок-фактура** — Proforma invoice (on sale.order and account.move)
* **Видаткова накладна** — Goods transfer / delivery note (on account.move)
* **Акт виконаних робіт** — Service act (on account.move)

All templates include:
* Company and partner requisites (ЄДРПОУ, ІПН, bank details)
* Amount in Ukrainian words (сума прописом)
* Discount totals
* Signature blocks
* Shared Ukrainian report styles and A4 paper format
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_account_base',
        'sale',
    ],
    'data': [
        'report/report_templates.xml',
        'report/invoice_report_inherit.xml',
        'report/report_rahunok.xml',
        'report/report_vydatkova.xml',
        'report/report_act.xml',
    ],
    'installable': True,
    'auto_install': False,
}
