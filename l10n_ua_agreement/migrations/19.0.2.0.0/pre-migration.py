"""19.0.2.0.0: власна модель `l10n_ua.agreement` замість OCA `agreement`.

Типи договорів із `data/agreement_type_data.xml` мали XML-id цього модуля на
моделі OCA `agreement.type`; ті самі XML-id тепер описують записи
`l10n_ua.agreement.type`. Щоб завантаження даних не спіткнулося об чужу модель,
відв'язуємо старі XML-id, запам'ятавши, який старий тип якому XML-id
відповідав, — post-migration зіставить їх із новими записами.
"""

from odoo.tools.sql import table_exists

# Представлення 1.x успадковували форми OCA й посилалися на поля, яких у 2.0 на
# моделі `agreement` уже немає. Odoo перевіряє всі представлення модуля після
# завантаження його даних — ще до того, як прибере застарілі записи, — тож
# видаляємо їх заздалегідь.
OLD_VIEWS = ('agreement_form_l10n_ua', 'agreement_tree_l10n_ua', 'agreement_search_l10n_ua')


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        DELETE FROM ir_ui_view WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'l10n_ua_agreement' AND model = 'ir.ui.view' AND name IN %s)
    """, (OLD_VIEWS,))
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'l10n_ua_agreement' AND model = 'ir.ui.view' AND name IN %s
    """, (OLD_VIEWS,))
    cr.execute("""
        CREATE TABLE IF NOT EXISTS l10n_ua_agreement_type_migr (
            old_id integer PRIMARY KEY, xmlid varchar NOT NULL)
    """)
    cr.execute("""
        INSERT INTO l10n_ua_agreement_type_migr (old_id, xmlid)
        SELECT res_id, name FROM ir_model_data
         WHERE module = 'l10n_ua_agreement' AND model = 'agreement.type'
        ON CONFLICT DO NOTHING
    """)
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'l10n_ua_agreement' AND model = 'agreement.type'
    """)
    if not table_exists(cr, 'agreement'):
        cr.execute("DROP TABLE l10n_ua_agreement_type_migr")
