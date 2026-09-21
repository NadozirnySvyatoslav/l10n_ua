{
    'name': 'Ukraine - NBU QR Payment Links',
    'version': '20.0.2.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Платіжні QR-коди за стандартом НБУ',
    'description': """
Генерація платіжних QR-кодів за стандартом НБУ (Постанова від 01.02.2021 №11)
на замовленнях, рахунках і друкованих формах.

Monobank Acquiring винесено в окремий модуль l10n_ua_mono_acquiring.
    """,
    'author': 'NDEV',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': ['l10n_ua_account_base', 'sale'],
    'data': [
        'security/ir.access.csv',
        'data/nbu_qr_data.xml',
        'views/res_config_settings_views.xml',
        'views/sale_order_views.xml',
        'views/account_move_views.xml',
        'report/payment_link_report.xml',
        'report/report_invoice_inherit.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
