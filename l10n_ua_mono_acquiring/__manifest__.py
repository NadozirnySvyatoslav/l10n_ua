{
    'name': 'Ukraine - Monobank Acquiring',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Приймання оплати карткою через Monobank Acquiring (еквайринг)',
    'description': """
Інтеграція з Monobank Acquiring (еквайринг)
===========================================

Приймання оплати карткою через мерчант-API Монобанку:

* Токен Acquiring на банківському журналі;
* Кнопка «Створити посилання Monobank» на замовленні та рахунку;
* Автоматичне підтвердження оплати через webhook (підтвердження замовлення,
  виставлення рахунку, реєстрація платежу);
* QR-код/посилання Monobank на друкованому рахунку.

Незалежний модуль — не пов'язаний із НБУ-QR (l10n_ua_payment_link) та із
синхронізацією виписок (l10n_ua_bank_mono).
    """,
    'author': 'NDEV',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': ['account', 'sale'],
    'external_dependencies': {
        'python': ['qrcode'],
    },
    'data': [
        'views/account_journal_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'report/mono_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
