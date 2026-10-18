"""19.0.2.0.0: договір — власна модель `l10n_ua.agreement`, поле `l10n_ua_agreement_id`.

Старі колонки `agreement_id` (посилання на OCA `agreement`) Odoo видалить у
кінці оновлення; переносимо значення через таблицю відповідностей, яку
залишила міграція l10n_ua_agreement 2.0 (той модуль оновлюється раніше).

Колонки створюємо й заповнюємо ще до завантаження моделей: інакше нове
збережене related-поле на `account.move.line` Odoo перерахував би для кожного
рядка проводок.
"""

from odoo.tools.sql import column_exists, create_column, table_exists

TABLES = ('account_move', 'account_move_line', 'account_payment', 'l10n_ua_debt_netting')


def migrate(cr, version):
    if not version or not table_exists(cr, 'l10n_ua_agreement_migr'):
        return
    for table in TABLES:
        if not column_exists(cr, table, 'agreement_id'):
            continue
        if not column_exists(cr, table, 'l10n_ua_agreement_id'):
            create_column(cr, table, 'l10n_ua_agreement_id', 'int4')
        cr.execute(f"""
            UPDATE {table} t SET l10n_ua_agreement_id = m.new_id
              FROM l10n_ua_agreement_migr m
             WHERE t.agreement_id = m.old_id
        """)
