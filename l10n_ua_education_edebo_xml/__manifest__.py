{
    'name': 'Ukraine - Education ЄДЕБО XML Import',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Education',
    'summary': 'Підтримка XML-формату обміну з ЄДЕБО (МОН)',
    'description': """
ЄДЕБО XML Import
================

Плагін до `l10n_ua_education_edebo`, що додає підтримку XML-формату
обміну з Єдиною державною електронною базою освіти (МОН).

* Override `_parse_custom()` для `file_format = 'custom'`
* Парсинг XML за припущеною структурою (нижче). Якщо реальна структура
  відрізняється — переозначте `_edebo_xml_extract_persons()` у дочірньому
  модулі під конкретний клієнтський контракт МОН.
* Експорт ще не реалізовано (окремий PR — потребує цифрового підпису)

## Припущена структура XML

```xml
<edebo>
  <students>
    <student>
      <last_name>Прізвище</last_name>
      <first_name>Імʼя</first_name>
      <middle_name>По-батькові</middle_name>
      <birthdate>2005-03-15</birthdate>
      <rnokpp>1234567890</rnokpp>
      <student_number>EDB-001</student_number>
      <member_type>student</member_type>
    </student>
    ...
  </students>
</edebo>
```

⚠️ Реальний формат ЄДЕБО варіюється — це лише робочий приклад.
    """,
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_education_edebo',
    ],
    'data': [],
    'demo': [],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
