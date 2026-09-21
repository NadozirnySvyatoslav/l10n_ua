{
    'name': 'Ukraine - Subconto: HR Departments',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localization',
    'summary': 'Bridge: use HR departments as a subconto dimension',
    'description': """
Ukraine - Subconto: HR Departments
==================================

Bridge module between ``l10n_ua_account_base`` and ``hr``.

Adds the HR department (Підрозділ) as an analytical dimension (субконто) on
journal items:

* ``l10n_ua.subconto.type`` record for ``hr.department``
* ``subconto_department_id`` quick access field on ``account.move.line``

The accounting base module stays free of any HR dependency; install this bridge
only when departments should be usable as subconto.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_account_base',
        'hr',
    ],
    'data': [
        'data/l10n_ua_subconto_data.xml',
        'views/l10n_ua_subconto_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
