{
    'name': 'Ukraine - HR Employee Transfer',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Localization',
    'summary': 'Переведення співробітника в іншу організацію (КЗпП ст. 36 п. 5)',
    'description': """
Ukraine HR Employee Transfer
============================

Wizard для переведення співробітника з однієї компанії в іншу групи компаній
за правилами КЗпП України (ст. 36 п. 5 — переведення на інше підприємство).

Що робить:

* Створює новий запис hr.employee у цільовій компанії з копіюванням
  персональних даних (ІПН/RNOKPP, паспорт, адреса, військовий облік, освіта).
* Опційно копіює банківські рахунки, особові документи, сімейні дані.
* Створює наказ "Про припинення трудового договору (переведенням)" у source
  та "Про прийняття на роботу (переведенням)" у target компаніях.
* Деактивує source employee.
* Підтримує режими балансу відпусток:
  reset (за замовчуванням, згідно змін 2022 р.) / transfer (за згодою сторін).
* Посилання cross-company через previous_employee_id / next_employee_id
  (для відображення повної трудової історії).

Залежить від:

* hr
* l10n_ua_hr_base — персональні дані, RNOKPP
* l10n_ua_hr_documents — модель hr.order (накази)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'mail',
        'l10n_ua_hr_base',
        'l10n_ua_hr_documents',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/hr_employee_transfer_wizard_views.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
