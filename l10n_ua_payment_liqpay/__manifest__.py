{
    'name': 'Ukraine - LiqPay Payment Provider',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': 'Оплата карткою на сайті та в порталі через LiqPay (ПриватБанк)',
    'description': """
Платіжний провайдер LiqPay
==========================

Стандартний платіжний провайдер Odoo (``payment.provider``) для інтернет-еквайрингу
LiqPay (ПриватБанк), Checkout API: працює в eCommerce, на порталі клієнта та в
платіжних посиланнях.

* покупець переходить на сторінку оплати LiqPay (форма ``data`` + ``signature``);
* статус приймається лише з callback на ``server_url`` з перевіреним підписом
  (SHA3-256) або із запиту статусу до API LiqPay;
* сума й валюта callback звіряються з транзакцією;
* повне й часткове повернення коштів через API (``action: refund``);
* валюти UAH, USD, EUR; тестовий режим — ключами ``sandbox_``.
    """,
    'author': 'NDEV',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['payment'],
    'data': [
        'views/payment_liqpay_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
