{
    'name': 'Ukraine - eCommerce Documents',
    'version': '19.0.1.0.0',
    'category': 'Website/Website',
    'summary': 'Акт / видаткова накладна з кнопки «Друк» після оплати в інтернет-магазині',
    'description': """
Bridge between the web shop and Ukrainian sale documents.

After a successful online payment the order confirmation page offers a Print button. Odoo
prints its order PDF there. Once the paid order has a posted customer invoice, this module
prints the primary document chosen for the company instead — акт or видаткова накладна (see
l10n_ua_sale_documents). Before that, the Рахунок-фактура is printed.
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['website_sale', 'l10n_ua_sale_documents'],
    'auto_install': True,
    'installable': True,
}
