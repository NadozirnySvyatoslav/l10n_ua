{
    'name': 'Ukraine - КЕП Signing',
    'version': '19.0.1.3.0',
    'category': 'Accounting/Localization',
    'summary': 'Переюзабельний клієнтський КЕП-підпис (IIT EndUser у браузері)',
    'description': """
Ukraine КЕП Signing
===================

Модуль-основа для кваліфікованого електронного підпису (КЕП) у браузері через
бібліотеку IIT EndUser (euscp) — так само, як вхід до cabinet.tax.gov.ua.
Приватний ключ і пароль **не покидають клієнта** — сервер лише отримує готові
base64-підписи.

Надає:

* `l10n_ua.sign.mixin` — успадкуйте у своїй моделі й реалізуйте
  `kep_prepare_signing()` / `kep_submit_signed()`, а кнопка викликає
  `action_kep_sign()` (за потреби з `mode` для кількох сценаріїв).
* Універсальне вікно підпису — OWL client action `l10n_ua_sign.kep_sign`, що
  відкривається поверх форми: що саме підписується, вибір ЦСК, файл-ключ +
  пароль, лінива підгрузка euscp за URL. Для дій лише з авторизацією
  (перевірка з'єднання, синхронізація) — одна кнопка; документи підписуються
  після звірки власника ключа.
* Зчитаний ключ — один на вкладку браузера, спільний для всіх модулів:
  20 хв після останнього використання пароль не потрібен (ключ на сервер не
  потрапляє; «Інший ключ» або закриття вкладки його забувають).
* Формати підпису: CAdES/P7S, конверт (підпис + шифрування на сертифікат
  отримувача), ASiC (для Дії).
* `/l10n_ua_sign/ca_proxy` — проксі до ЦСК для бібліотеки (лише хости зі
  списку ЦСК).

Споживачі: реєстрація ПН в ЄРПН, податкові декларації, запити до ДПС, тощо.

Файли бібліотеки IIT euscp пропрієтарні — див. static/src/lib/euscp/README.md.
Там же — обов'язкова вимога до збірки: підтримка ДСТУ 7564:2014 («Купина»)
з 01.09.2026, і команда, якою це перевіряється в конкретних файлах.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://1c-to-odoo.many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'web',
    ],
    'data': [],
    'assets': {
        'web.assets_backend': [
            # euscp НЕ бандлимо — worker ~16МБ вантажиться за URL при підписі.
            'l10n_ua_sign/static/src/css/kep_sign.css',
            'l10n_ua_sign/static/src/js/kep_sign_service.js',
            'l10n_ua_sign/static/src/js/kep_sign_action.js',
            'l10n_ua_sign/static/src/xml/kep_sign_action.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
