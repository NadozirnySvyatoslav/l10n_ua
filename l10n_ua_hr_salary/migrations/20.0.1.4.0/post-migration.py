"""Перерахувати чернетки авансів, збережені за неконвертованим окладом.

`gross_amount` — збережене обчислюване поле, тож суми, пораховані до
переходу на курс, лишаються в базі як є: працівник із окладом 1000 USD має
в чернетці аванс 500 грн замість двадцяти з гаком тисяч. Нове обчислення
саме по собі їх не зачепить — воно спрацює лише коли зміниться якась із
залежностей.

Чіпаємо винятково чернетки: підтверджений чи виплачений аванс — це вже
факт, а не розрахунок, і переписувати його заднім числом не можна.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Advance = env['hr.salary.advance']
    drafts = Advance.search([('state', '=', 'draft')])
    if not drafts:
        return

    # Кожна чернетка окремо, і кожна у своїй точці збереження. Перерахунок
    # валютного окладу без курсу кидає UserError — одним махом він зірвав би
    # оновлення модуля цілком, а невдале оновлення гірше за занижену суму в
    # чернетці, яку однаково перерахує перше ж редагування.
    recomputed = skipped = 0
    for advance in drafts:
        try:
            with env.cr.savepoint():
                env.add_to_compute(Advance._fields['gross_amount'], advance)
                advance.flush_recordset(['gross_amount'])
        except UserError:
            skipped += 1
        else:
            recomputed += 1

    _logger.info(
        'l10n_ua_hr_salary 20.0.1.4.0: перераховано %s чернеток авансу',
        recomputed)
    if skipped:
        _logger.warning(
            'l10n_ua_hr_salary 20.0.1.4.0: %s чернеток авансу лишились із '
            'сумою за неконвертованим окладом — для них немає курсу валюти. '
            'Внесіть курс і перевідкрийте нарахування.', skipped)
