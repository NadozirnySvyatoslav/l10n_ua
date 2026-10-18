{
    'name': 'Ukraine - Agreements (Договори)',
    'version': '19.0.2.0.0',
    'category': 'Sales/Localization',
    'summary': 'Agreements with customers and vendors: numbering, amendments, '
               'КЕП signature, printed agreement and service act',
    'description': """
Ukraine Agreements (Договори)
=============================

Облік договорів з покупцями та постачальниками, без залежностей від OCA:

* Договір як окремий документ: номер із послідовності, тип, сторона (покупець /
  постачальник), сума, строк дії, відповідальний, історія змін;
* Стан: Чернетка → На підписанні → Підписаний → Завершений (автоматично після
  дати завершення) / Скасований;
* Підпис нашої сторони КЕП у браузері (``l10n_ua_sign``): підписаний файл
  ``.p7s`` зберігається в договорі; документ, підписаний обома сторонами, —
  окремим вкладенням;
* Додаткові угоди як дочірні договори;
* Типи договорів із шаблоном предмета договору;
* Друкована форма договору та акта наданих послуг;
* Договір у замовленні на продаж, лічильник договорів у контрагента.

Взаєморозрахунки в розрізі договорів — ``l10n_ua_agreement_account``;
періодичні рахунки (OCA ``contract``) — ``l10n_ua_agreement_contract``.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'l10n_ua_sign',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/l10n_ua_agreement_security.xml',
        'data/ir_sequence_data.xml',
        'data/agreement_type_data.xml',
        'report/agreement_report.xml',
        'report/agreement_report_templates.xml',
        'views/agreement_views.xml',
        'views/sale_partner_views.xml',
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
