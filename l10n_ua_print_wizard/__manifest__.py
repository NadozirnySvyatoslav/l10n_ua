{
    'name': 'Ukraine - Print Wizard for Invoices',
    'version': '19.0.1.0.2',
    'category': 'Accounting/Localization',
    'summary': 'The "Print" button on invoices asks which report to print',
    'description': """
Ukraine - Print Wizard for Invoices
===================================

The "Print" button on a posted invoice or bill opens a dialog with the same
reports as the gear menu → Print (Рахунок-фактура, Акт, Видаткова накладна,
Invoice PDF, …) instead of always printing the default invoice report.

* The default report (partner / journal template, or Invoice PDF) is preselected.
* Only reports the user can see in the gear menu are listed (groups, access rights, report domain).
* With a single available report the button prints it right away.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/l10n_ua_print_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
