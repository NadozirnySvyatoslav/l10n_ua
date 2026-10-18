from odoo.tools.sql import table_exists


def post_init_hook(env):
    """Зв'язки періодичних договорів, збережені міграцією l10n_ua_agreement 2.0.

    До 2.0 поле `contract.contract.agreement_id` визначав сам l10n_ua_agreement;
    його колонку видалено, а пари (договір OCA contract → новий договір) лишено
    в таблиці `l10n_ua_agreement_contract_migr`.
    """
    cr = env.cr
    if not table_exists(cr, 'l10n_ua_agreement_contract_migr'):
        return
    cr.execute("""
        UPDATE contract_contract c SET l10n_ua_agreement_id = m.agreement_id
          FROM l10n_ua_agreement_contract_migr m
         WHERE c.id = m.contract_id
    """)
    cr.execute("DROP TABLE l10n_ua_agreement_contract_migr")
