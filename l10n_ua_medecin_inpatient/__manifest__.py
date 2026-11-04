{
    'name': 'Ukraine - Medecin Inpatient',
    'version': '19.0.1.1.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Стаціонар: епізод стаціонарного лікування (пролікований випадок), ліжко-дні',
    'description': """
Medecin Inpatient
=================

* Епізод стаціонарного лікування (пролікований випадок) —
  l10n_ua.medecin.admission: госпіталізація, виписка, результат лікування,
  ліжко-дні
* Номер медичної карти стаціонарного хворого (ф. 003/о) — автонумерація
* Відділення стаціонару — l10n_ua.medecin.department (профіль, завідувач,
  обчислюваний ліжковий фонд)
* Ліжковий фонд — l10n_ua.medecin.bed (палата, номер, профіль ліжка,
  дати розгортання/згортання), ліжко в епізоді, переведення між відділеннями
* Ф. 007/о «Листок обліку руху хворих і ліжкового фонду стаціонару» за добу
  (PDF) і показники за період: днів зайнятості ліжка на рік, обіг ліжка,
  середня тривалість перебування, летальність

Регуляторна база:

* Наказ МОЗ України від 14.02.2012 № 110 (форми первинної облікової
  документації: 003/о, 066/о, 007/о)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_clinical',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'views/l10n_ua_medecin_department_views.xml',
        'views/l10n_ua_medecin_admission_views.xml',
        'views/menu_views.xml',
        'security/bed_security.xml',
        'views/l10n_ua_medecin_bed_views.xml',
        'views/l10n_ua_medecin_bed_report_views.xml',
        'report/report_007o.xml',
        'views/menu_bed_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
