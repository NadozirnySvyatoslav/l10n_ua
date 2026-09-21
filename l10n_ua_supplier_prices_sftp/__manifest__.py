{
    'name': 'Ukraine - Supplier Prices SFTP Fetcher',
    'version': '20.0.1.0.0',
    'category': 'Purchases/Localization',
    'summary': 'SFTP fetcher для імпорту прайсів постачальників',
    'description': """
SFTP fetcher extension for l10n_ua_supplier_prices_base.

Додає тип 'sftp' у fetcher_type на supplier.price.source.

Connection config (JSON на source):
{
  "host": "sftp.supplier.com",         # обов'язково
  "port": 22,
  "username": "...",                    # обов'язково
  "password": "...",                    # або key_file
  "key_file": "/path/to/key.pem",      # альтернатива до password
  "key_passphrase": "...",             # для зашифрованого ключа
  "remote_path": "/exports/latest.xlsx",  # обов'язково
  "host_key_policy": "auto_add" | "reject" | "warning"
}

Безпека:
- host_key_policy default 'reject' (паніка якщо невідомий хост) — production
- 'auto_add' — приймає невідомі хости (development only)
- 'warning' — приймає з warning у лог

⚠️ Credentials наразі зберігаються plain text у connection_config.
Production: винести в ir.config_parameter або зашифроване сховище.
""",
    'author': 'Svyatoslav Nadozirny',
    'website': 'https://many2one.online',
    'license': 'LGPL-3',
    'depends': [
        'l10n_ua_supplier_prices_base',
    ],
    'external_dependencies': {'python': ['paramiko']},
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
    'price': 0,
    'currency': 'EUR',
}
