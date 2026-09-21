{
    'name': 'Ukraine - Education Base',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Education',
    'summary': 'Облік освітніх закладів: типи установ, контингент, навчальні групи',
    'description': """
Ukraine Education Base
======================

Базовий модуль для українських освітніх установ (заклади дошкільної,
загальної середньої, професійної та вищої освіти).

* Тип закладу освіти (ЗДО, ШНЗ, ПТУ, ЗВО I-IV рівнів)
* Навчальний рік (наприклад «2025/2026») з активним прапорцем
* Навчальні групи / класи / курси з рівнем і профілем
* Контингент: учні/студенти/вихованці з повним lifecycle
  (applicant → enrolled → studying → graduated / expelled / transferred)
* Прив'язка до `res.partner` (як до фізособи) та опціонально
  до `hr.employee` (якщо це працівник, який паралельно навчається)

Регуляторна база:
* Закон України «Про освіту» № 2145-VIII від 05.09.2017
* Закон України «Про вищу освіту» № 1556-VII від 01.07.2014
* Закон України «Про повну загальну середню освіту» № 463-IX від 16.01.2020
* Закон України «Про дошкільну освіту» № 2628-III від 11.07.2001
* Закон України «Про професійно-технічну освіту» № 103/98-ВР від 10.02.1998
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
        'security/multicompany_security.xml',
        'data/l10n_ua_education_academic_year_data.xml',
        'views/res_company_views.xml',
        'views/l10n_ua_education_academic_year_views.xml',
        'views/l10n_ua_education_group_views.xml',
        'views/l10n_ua_education_contingent_member_views.xml',
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
