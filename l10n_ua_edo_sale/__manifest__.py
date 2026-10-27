{
    'name': 'Ukraine - EDO for Sales Orders',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Localization',
    'summary': 'Надсилання рахунку-фактури із замовлення продажу у ЕДО',
    'description': """
Ukraine - EDO for Sales Orders
==============================

«Надіслати у ЕДО» on a sales order: the Рахунок-фактура of l10n_ua_doc_reports
comes first. The EDO status is on the order form.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['sale', 'l10n_ua_edo'],
    'data': [
        'views/edo_send_action.xml',
        'views/sale_order_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'auto_install': True,
}
