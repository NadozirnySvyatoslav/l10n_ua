{
    'name': 'Ukraine - Medecin Inpatient',
    'version': '19.0.1.2.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Стаціонар: епізод стаціонарного лікування (пролікований випадок), ліжко-дні',
    'description': """
Medecin Inpatient
=================

* Епізод стаціонарного лікування (пролікований випадок) —
  l10n_ua.medecin.admission: госпіталізація, виписка, результат лікування,
  ліжко-дні
* Номер медичної карти стаціонарного хворого (ф. 003/о) — автонумерація
* Відділення стаціонару — l10n_ua.medecin.department (мінімальний довідник;
  ліжковий фонд і ф. 007/о — окремою задачею)
* Типізовані діагнози епізоду (при госпіталізації, клінічний, заключний,
  патолого-анатомічний, супутні, ускладнення); рівно один заключний
  діагноз у виписаного епізоду
* Медичні (хірургічні) втручання — l10n_ua.medecin.procedure: дата, хірург,
  анестезіолог, вид знеболення, екстреність, ускладнення; довідник кодів
  втручань l10n_ua.medecin.procedure.type (під НК 026:2021 / АКМВ)

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
        'views/l10n_ua_medecin_diagnosis_views.xml',
        'views/l10n_ua_medecin_procedure_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
