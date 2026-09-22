"""Ключі КЕП більше не зберігаються на сервері (#324).

Підпис перенесено в браузер (l10n_ua_sign), тож поле kep_key_file зникає з
моделі. Вкладення з уже завантаженими ключами самі не видаляться — лишилися б
у базі й файловому сховищі осиротілими. Прибираємо їх тут, разом зі стовпцями
імені ключа та шляхів до нативної бібліотеки IIT.

Майстер пароля теж зник, але Odoo лишає таблицю transient-моделі, а в ній
паролі КЕП лежали відкритим текстом до вакууму — таблицю видаляємо.
"""

import logging

from odoo import api, SUPERUSER_ID
from odoo.tools import SQL
from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

MODEL = 'l10n_ua.tax.cabinet.config'
TABLE = 'l10n_ua_tax_cabinet_config'
DROPPED_COLUMNS = ('kep_key_filename', 'iit_lib_path', 'iit_cert_path')
PASSWORD_WIZARD_TABLE = 'l10n_ua_tax_cabinet_password_wizard'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    keys = env['ir.attachment'].search([
        ('res_model', '=', MODEL),
        ('res_field', '=', 'kep_key_file'),
    ])
    if keys:
        count = len(keys)
        keys.unlink()
        _logger.info("l10n_ua_tax_cabinet: видалено збережених ключів КЕП: %s", count)

    for column in DROPPED_COLUMNS:
        if column_exists(cr, TABLE, column):
            cr.execute(SQL(
                "ALTER TABLE %s DROP COLUMN %s",
                SQL.identifier(TABLE), SQL.identifier(column),
            ))

    if table_exists(cr, PASSWORD_WIZARD_TABLE):
        cr.execute(SQL("DROP TABLE %s CASCADE", SQL.identifier(PASSWORD_WIZARD_TABLE)))
        _logger.info("l10n_ua_tax_cabinet: видалено таблицю майстра пароля КЕП")
