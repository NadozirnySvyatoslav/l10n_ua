{
    'name': 'Ukraine - Medecin Base',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Healthcare',
    'summary': 'Базис для українських закладів охорони здоров\'я',
    'description': """
Ukraine Medecin Base
====================

Базовий модуль для українських закладів охорони здоров'я: лікарень,
поліклінік, центрів первинної медико-санітарної допомоги (ЦПМСД),
амбулаторій сімейної медицини (АСМД), станцій швидкої медичної
допомоги (СМД), діагностичних центрів.

* Тип закладу охорони здоров'я (lікарня / поліклініка / ЦПМСД / АСМД /
  СМД / діагностичний центр / санаторій тощо)
* Ліцензія МОЗ на медичну діяльність
* Прив'язка до НСЗУ як надавача медичних послуг
* Спеціалізації / профілі (терапія, хірургія, педіатрія, СМП, ...)

Регуляторна база:
* Закон України «Основи законодавства про охорону здоров'я»
* Постанова КМУ № 285 від 27.03.2019 — ліцензійні умови для меддіяльності
* Закон України «Про державні фінансові гарантії медичного обслуговування
  населення» (НСЗУ)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'l10n_ua_account_base',
    ],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/l10n_ua_medecin_specialty_data.xml',
        'views/res_company_views.xml',
        'views/l10n_ua_medecin_specialty_views.xml',
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
