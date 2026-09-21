{
    'name': 'Ukraine - Supplier Prices XML Parser',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'XML парсер для імпорту прайсів постачальників',
    'description': """
XML parser extension for l10n_ua_supplier_prices_base.

Додає тип 'xml' у parser_type на supplier.price.source.

Mapping:
- record_path: XPath до елементів-записів (наприклад '//product' або
  '/catalog/items/item')
- source_path на полях: XPath відносний від record. Підтримує:
    './code/text()'      → текст вкладеного елемента
    '@sku'               → значення атрибута
    './price/@value'     → атрибут вкладеного елемента
    'string(./name)'     → string() якщо потрібно

Parser config (JSON на mapping):
- namespaces: {"ns": "http://example.com/schema"} — для elements з NS
  тоді у source_path: './ns:code/text()'
- encoding: примусова заміна кодування (за замовчуванням з XML declaration)

XML особливості:
- Підтримуються ns-префіксні XPath запити через namespaces map
- 1С вивантаження часто use cp1251/windows-1251 у XML declaration
- text() та @attr — типові патерни
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_supplier_prices_base',
    ],
    'external_dependencies': {'python': ['lxml']},
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
