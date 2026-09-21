{
    'name': 'Ukraine - Supplier Prices XLSX Parser',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'XLSX (Excel) парсер для імпорту прайсів постачальників',
    'description': """
XLSX parser extension for l10n_ua_supplier_prices_base.

Додає тип 'xlsx' у parser_type на supplier.price.source.

Parser config (JSON на mapping):
- sheet_name: ім'я або індекс листа (default — перший лист)
- header_row: номер рядка з заголовками (1-based, default 1)
- has_header: True (колонка за назвою) / False (за літерою/індексом)
- skip_rows: скільки рядків даних пропустити після header (default 0)

Field source_path:
- has_header=True: назва колонки (наприклад "Артикул", "Ціна")
- has_header=False: літера колонки ("A", "B", "AC") або індекс ("0", "1")

Excel-специфіка:
- Дати з типом datetime повертаються як date через trasform parse_date
  з порожнім параметром (вже date — не парситься повторно)
- Числові ціни вже float — transform 'to_float' опційний
- Текстові ціни ('15,50') обробляються через transform 'to_float'
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_supplier_prices_base',
    ],
    'external_dependencies': {'python': ['openpyxl']},
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
