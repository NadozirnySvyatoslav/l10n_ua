"""19.0.2.0.0: перенести договори з OCA `agreement` у `l10n_ua.agreement`.

Колонки, які до 2.0 додавав цей модуль у таблицю `agreement` (стан, основний
договір, предмет, сума…), Odoo видалить у кінці оновлення, тож дані беремо
тут, поки вони є. Відповідність старих і нових id лишаємо в таблиці
`l10n_ua_agreement_migr` — нею користуються міграції мостів
(`l10n_ua_agreement_account`, `l10n_ua_agreement_contract`).

Самі OCA-модулі (`agreement`, `agreement_sale`, `sign_oca`, `contract`) не
видаляються; меню OCA-договорів ховаємо, щоб не було двох застосунків
«Договори». Після перевірки їх можна деінсталювати.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

# Колонки, що їх додавав цей модуль 1.x у таблицю OCA `agreement`.
OWN_COLUMNS = ('state', 'parent_agreement_id', 'subject', 'currency_id',
               'amount_total', 'signed_filename')
STATES = {'draft', 'to_sign', 'signed', 'expired', 'cancelled'}


def _migrate_types(cr, env):
    """Старий id типу → новий запис l10n_ua.agreement.type."""
    Type = env['l10n_ua.agreement.type'].with_context(active_test=False)
    by_xmlid = {}
    if table_exists(cr, 'l10n_ua_agreement_type_migr'):
        cr.execute("SELECT old_id, xmlid FROM l10n_ua_agreement_type_migr")
        by_xmlid = dict(cr.fetchall())
    cr.execute("SELECT id, name, domain, active FROM agreement_type ORDER BY id")
    mapping = {}
    for old_id, name, domain, active in cr.fetchall():
        new = env.ref(f'l10n_ua_agreement.{by_xmlid[old_id]}', raise_if_not_found=False) \
            if old_id in by_xmlid else None
        if not new:
            new = Type.search([('name', '=', name)], limit=1) or Type.create({
                'name': name,
                'direction': domain if domain in ('sale', 'purchase') else 'sale',
                'active': bool(active),
            })
        mapping[old_id] = new.id
    return mapping


def _migrate_agreements(cr, env, type_map):
    own = {col: column_exists(cr, 'agreement', col) for col in OWN_COLUMNS}
    select = ', '.join(col if own[col] else f'NULL AS {col}' for col in OWN_COLUMNS)
    cr.execute(f"""
        SELECT id, code, name, partner_id, company_id, agreement_type_id, domain,
               active, signature_date, start_date, end_date, is_template, {select}
          FROM agreement ORDER BY id
    """)
    rows = cr.dictfetchall()
    Agreement = env['l10n_ua.agreement'].with_context(
        tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
    company = env.company
    mapping = {}
    for row in rows:
        if not row['partner_id']:
            # Шаблони OCA без контрагента: їх роль тепер виконують типи договорів.
            _logger.info("agreement %s (%s) has no partner, skipped", row['id'], row['code'])
            continue
        vals = {
            'code': row['code'] or '/',
            'name': row['name'] or row['code'] or '/',
            'partner_id': row['partner_id'],
            'company_id': row['company_id'] or company.id,
            'direction': row['domain'] if row['domain'] in ('sale', 'purchase') else 'sale',
            'agreement_type_id': type_map.get(row['agreement_type_id']),
            'active': bool(row['active']) and not row['is_template'],
            'signature_date': row['signature_date'],
            'start_date': row['start_date'],
            'end_date': row['end_date'],
            'state': row['state'] if row['state'] in STATES else 'draft',
            'subject': row['subject'],
            'amount_total': row['amount_total'] or 0.0,
            'signed_filename': row['signed_filename'],
        }
        if row['currency_id']:
            vals['currency_id'] = row['currency_id']
        mapping[row['id']] = Agreement.create(vals).id
    for row in rows:
        if row['parent_agreement_id'] and row['id'] in mapping \
                and row['parent_agreement_id'] in mapping:
            Agreement.browse(mapping[row['id']]).parent_id = mapping[row['parent_agreement_id']]
    return mapping


def _move_records(cr, mapping):
    """Історія, підписники, активності й вкладення — на нові записи."""
    cr.execute("SELECT id FROM ir_model WHERE model = 'l10n_ua.agreement'")
    new_model_id = cr.fetchone()[0]
    for table, model_col, res_col in (
        ('mail_message', 'model', 'res_id'),
        ('mail_followers', 'res_model', 'res_id'),
        ('mail_activity', 'res_model', 'res_id'),
        ('ir_attachment', 'res_model', 'res_id'),
    ):
        extra = ', res_model_id = %(model_id)s' if table == 'mail_activity' else ''
        cr.execute(f"""
            UPDATE {table} t
               SET {model_col} = 'l10n_ua.agreement', {res_col} = m.new_id{extra}
              FROM l10n_ua_agreement_migr m
             WHERE t.{model_col} = 'agreement' AND t.{res_col} = m.old_id
        """, {'model_id': new_model_id})
    # Підписаний документ лежав у полі `signed_document` (attachment=True) —
    # ім'я поля те саме, тож вкладення вже прив'язане правильно.


def migrate(cr, version):
    if not version or not table_exists(cr, 'agreement'):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    type_map = _migrate_types(cr, env) if table_exists(cr, 'agreement_type') else {}
    mapping = _migrate_agreements(cr, env, type_map)

    cr.execute("""
        CREATE TABLE IF NOT EXISTS l10n_ua_agreement_migr (
            old_id integer PRIMARY KEY, new_id integer NOT NULL)
    """)
    for old_id, new_id in mapping.items():
        cr.execute("INSERT INTO l10n_ua_agreement_migr VALUES (%s, %s) ON CONFLICT DO NOTHING",
                   (old_id, new_id))
    _move_records(cr, mapping)

    # Договір у замовленнях (поле OCA agreement_sale).
    if column_exists(cr, 'sale_order', 'agreement_id'):
        cr.execute("""
            UPDATE sale_order so SET l10n_ua_agreement_id = m.new_id
              FROM l10n_ua_agreement_migr m
             WHERE so.agreement_id = m.old_id AND so.l10n_ua_agreement_id IS NULL
        """)
    # Періодичні договори OCA: колонку цього модуля буде видалено, а міст
    # l10n_ua_agreement_contract може встановитися пізніше — зберігаємо зв'язки.
    if column_exists(cr, 'contract_contract', 'agreement_id'):
        cr.execute("""
            CREATE TABLE IF NOT EXISTS l10n_ua_agreement_contract_migr AS
            SELECT c.id AS contract_id, m.new_id AS agreement_id
              FROM contract_contract c
              JOIN l10n_ua_agreement_migr m ON m.old_id = c.agreement_id
        """)

    menu = env.ref('agreement.agreement_menu_root', raise_if_not_found=False)
    if menu:
        menu.active = False
    if table_exists(cr, 'l10n_ua_agreement_type_migr'):
        cr.execute("DROP TABLE l10n_ua_agreement_type_migr")
    _logger.info("l10n_ua_agreement: %s agreements moved from OCA agreement", len(mapping))
