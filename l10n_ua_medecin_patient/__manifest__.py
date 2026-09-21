{
    'name': 'Ukraine - Medecin Patient',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Пацієнти медичних закладів та декларації з лікарем (ПМД)',
    'description': """
Ukraine Medecin Patient
=======================

Облік пацієнтів медичного закладу і декларацій з лікарем первинної
медико-санітарної допомоги.

* Модель пацієнта (`l10n_ua.medecin.patient`) з прив'язкою до `res.partner`
* Декларація пацієнта з лікарем (`l10n_ua.medecin.declaration`) — основа для
  розрахунку капітації НСЗУ. Lifecycle: draft → active → terminated.
* Прив'язка пацієнта до закладу, лікаря (`hr.employee`), категорії віку
  для коректного капітаційного коефіцієнта НСЗУ
* RNOKPP пацієнта (для дорослих) або свідоцтво про народження (для дітей)

Регуляторна база:
* Закон України «Про державні фінансові гарантії медичного обслуговування
  населення» (НСЗУ)
* Наказ МОЗ № 503 від 19.03.2018 — Порядок вибору лікаря ПМД
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_base',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/l10n_ua_medecin_patient_views.xml',
        'views/l10n_ua_medecin_declaration_views.xml',
        'views/menu_views.xml',
    ],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
