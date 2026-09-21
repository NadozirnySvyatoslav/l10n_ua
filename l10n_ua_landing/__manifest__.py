{
    'name': 'Ukraine Localization: Demo Landing Page',
    'summary': 'Презентабельна головна сторінка (/) для демо-сервера l10n_ua',
    'description': """
Замінює дефолтну головну сторінку Odoo Website на презентабельний лендинг
української локалізації (many2one). Публічні відвідувачі бачять опис рішення
та кнопку «Спробувати демо»; внутрішні користувачі одразу потрапляють у /odoo.
""",
    'version': '20.0.1.0.0',
    'category': 'Website',
    'author': 'many2one',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': ['website'],
    'data': [
        'views/landing_templates.xml',
        'views/website_templates.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
