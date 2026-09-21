{
    'name': 'Ukraine - Medecin Clinical',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Клінічна картка пацієнта: прийоми, діагнози, МКХ-10',
    'description': """
Medecin Clinical
================

* Модель прийому (encounter) — l10n_ua.medecin.encounter
* Діагноз з прив'язкою до МКХ-10 — l10n_ua.medecin.diagnosis
* Каталог МКХ-10 — l10n_ua.medecin.icd10 (стартова вибірка ~40 кодів,
  повний реєстр — окремий PR з імпортом CSV)
* Хронічні стани, алергії, поточні ліки — l10n_ua.medecin.condition,
  l10n_ua.medecin.allergy

Регуляторна база:
* МКХ-10 (10-та редакція з адаптацією МОЗ України)
* Наказ МОЗ № 110 (форми первинної облікової документації)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_medecin_patient',
    ],
    'data': [
        'security/ir.access.csv',
        'security/multicompany_security.xml',
        'data/l10n_ua_medecin_icd10_data.xml',
        'views/l10n_ua_medecin_icd10_views.xml',
        'views/l10n_ua_medecin_encounter_views.xml',
        'views/l10n_ua_medecin_condition_views.xml',
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
