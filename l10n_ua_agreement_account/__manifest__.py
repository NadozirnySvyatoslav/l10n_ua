{
    'name': 'Ukraine - Agreements Accounting (Взаєморозрахунки за договорами)',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Взаєморозрахунки у розрізі договорів: договір у рахунках, '
               'платежах та акті звірки',
    'description': """
Ukraine Agreements Accounting
=============================

Проброс договору (``agreement_id``) у бухгалтерські транзакції для ведення
взаєморозрахунків та ОСВ (361/631) у розрізі договорів:

* Поле «Договір» на рахунках (``account.move``), рядках проводок
  (``account.move.line``) та платежах (``account.payment``);
* Автоматичне успадкування договору із замовлення на продаж при виставленні
  рахунку;
* Автоматичне проставлення договору на платежі при реєстрації оплати рахунків
  одного договору;
* Фільтр та групування взаєморозрахунків за договором;
* Акт звірки за конкретним договором (розширення майстра акту звірки).

Міст між ``l10n_ua_agreement`` та ``l10n_ua_accounting``.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_agreement',
        'l10n_ua_accounting',
    ],
    'data': [
        'views/account_move_views.xml',
        'views/account_payment_views.xml',
        'wizard/reconciliation_act_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
