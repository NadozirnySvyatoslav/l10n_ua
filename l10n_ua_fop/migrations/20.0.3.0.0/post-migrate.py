"""Ліміти груп ЄП і мінзарплата — з довідника, а не з констант (#325).

Групи з даних модуля під noupdate, тож новий множник лімітів самі не
отримають — проставляємо його за кодом групи (п. 291.4 ПКУ).

Мінзарплата й ліміт у декларації тепер обчислюються з довідника
l10n_ua.min.wage. Перераховуємо лише незакриті декларації: подані й
прийняті — це вже поданий документ, їхні суми не чіпаємо.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Граничний дохід групи — у мінімальних зарплатах на 1 січня року.
LIMIT_MIN_WAGES = {'1': 167, '2': 834, '3': 1167, '3_vat': 1167}
RECOMPUTED_FIELDS = (
    'min_wage', 'income_limit', 'income_limit_exceeded',
    'esv_base', 'esv_amount', 'single_tax', 'total_payable',
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    groups = env['l10n_ua.fop.group'].with_context(active_test=False).search([])
    for group in groups:
        if not group.limit_min_wages and group.code in LIMIT_MIN_WAGES:
            group.limit_min_wages = LIMIT_MIN_WAGES[group.code]

    Declaration = env['l10n_ua.fop.declaration']
    open_declarations = Declaration.search([('state', 'in', ('draft', 'calculated'))])
    if open_declarations:
        for fname in RECOMPUTED_FIELDS:
            env.add_to_compute(Declaration._fields[fname], open_declarations)
        env.flush_all()
    _logger.info(
        "l10n_ua_fop: множники лімітів груп проставлено, перераховано декларацій: %s",
        len(open_declarations))
