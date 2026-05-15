{
    'name': 'Ukraine - HR Certificates',
    'version': '19.0.1.1.0',
    'category': 'Human Resources/Localization',
    'summary': 'Standard HR certificates and references for Ukrainian companies',
    'description': """
Ukraine HR Certificates Module
==============================

This module provides standard HR certificates and references commonly issued by HR departments:

* Employment certificate (Довідка про роботу)
* Salary certificate (Довідка про заробітну плату)
* Work experience certificate (Довідка про стаж роботи)
* Income certificate (Довідка про доходи)
* Character reference (Характеристика)
* Bank certificate (Довідка для банку)
* Vacation certificate (Довідка про відпустку)
* Custom certificates with templates

Features:
* Certificate types with configurable templates
* Automatic data population from employee records
* Print-ready document generation
* Certificate registry with numbering
* Request workflow (draft -> approved -> issued)

Requires l10n_ua_hr_base module.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_hr_base',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/hr_certificate_type_data.xml',
        'views/hr_certificate_type_views.xml',
        'views/hr_certificate_views.xml',
        'views/hr_employee_views.xml',
        'views/menu_views.xml',
        'report/hr_certificate_report.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
