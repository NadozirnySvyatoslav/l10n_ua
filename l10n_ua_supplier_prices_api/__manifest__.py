{
    'name': 'Ukraine - Supplier Prices API Fetcher',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'HTTP API fetcher для імпорту прайсів постачальників',
    'description': """
API (HTTP) fetcher extension for l10n_ua_supplier_prices_base.

Додає тип 'api' у fetcher_type на supplier.price.source.

Connection config (JSON на source):
{
  "url": "https://supplier.com/api/pricelist",      # обов'язково
  "method": "GET",                                   # GET або POST
  "auth_type": "none" | "basic" | "bearer" | "api_key_header",
  "username": "...",       # для basic
  "password": "...",       # для basic
  "token": "...",          # для bearer / api_key_header
  "header_name": "X-API-Key",  # для api_key_header
  "headers": {"Accept": "application/json"},  # extra headers
  "params": {"format": "json"},  # query params
  "body": {},              # JSON body для POST
  "response_type": "file" | "json_indirect",
  "json_indirect_path": "data.download_url"  # якщо response_type=json_indirect
}

Режими:
- response_type=file (default): відповідь — це сам файл, зберігається як raw_file
- response_type=json_indirect: відповідь — JSON з URL до файлу,
  з path витягуємо URL і робимо другий запит

Timeout — з source.fetch_timeout (connect + read).
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_supplier_prices_base',
    ],
    'external_dependencies': {'python': ['requests']},
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
