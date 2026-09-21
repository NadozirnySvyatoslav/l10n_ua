{
    'name': 'Ukraine - Supplier Prices CSV Parser',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'CSV парсер для імпорту прайсів постачальників',
    'description': """
CSV parser extension for l10n_ua_supplier_prices_base.

Додає тип 'csv' у parser_type на supplier.price.source.

Parser config (JSON на mapping):
- delimiter: розділювач полів, default ','
- encoding: кодування файлу, default 'utf-8'.
  Fallback при помилці: utf-8-sig, windows-1251, cp1251
- has_header: True (колонка за назвою) / False (колонка за індексом)
- skip_rows: скільки рядків пропустити на початку файлу
- quotechar: символ цитування, default '"'

Field source_path при has_header=True — назва колонки.
При has_header=False — індекс колонки як число у рядку (0-based): "0", "1", ...

Підтримує українські прайси з:
- windows-1251 / cp1251 кодуванням
- комами як десятковим роздільником (через transform replace_comma або to_float)
- крапкою з комою (;) як роздільником полів
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_supplier_prices_base',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
