{
    'name': 'Ukraine - Education Meals',
    'version': '20.0.1.1.0',
    'category': 'Human Resources/Education',
    'summary': 'Облік дитячого харчування для ЗДО і ШНЗ',
    'description': """
Education Meals
===============

* Меню (`l10n_ua.meal.menu`) — щоденні / тижневі меню
* Технологічні картки страв (`l10n_ua.meal.recipe`) — інгредієнти
  пов'язуються з товарами (кількість + одиниця виміру), що дає
  собівартість порції й меню та витрату продуктів за меню
* Облік відвідуваності (`l10n_ua.meal.attendance`) — для розрахунку
  фактичної кількості порцій
* Вікові групи: ЗДО 1-3 / 3-6 років, школа 1-4 / 5-11 класи,
  коледж / ЗФПО 15-19 років

Регуляторна база:
* Постанова КМУ № 1545 (норми харчування у ЗДО)
* Постанова КМУ № 305 (норми у школах)
* Наказ МОЗ № 1073 (фізіологічні норми)
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_education_base',
        'product',
    ],
    'data': [
        'security/ir.access.csv',
        'views/l10n_ua_meal_recipe_views.xml',
        'views/l10n_ua_meal_menu_views.xml',
        'views/l10n_ua_meal_attendance_views.xml',
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
