"""TEACH_HOURLY не входить у середню для відпусток (#417, Р1).

Ставки погодинної оплати ПКМУ № 1078 уже включають оплату за дні відпустки
(примітка 4 до ставок), тож у середній для відпускних ці години рахувались би
вдруге. У середньомісячний за 2 місяці (вихідна допомога, п. 2 абз. 4
Порядку № 100) вони входять, тому is_basic_salary не чіпаємо, а ставимо нову
ознаку l10n_ua_vacation_included. Запис виду нарахування — noupdate, тому
ознаку в наявних базах ставимо тут. Поле нове, тож вручну його ще ніхто не
змінював; інші види лишаються з default False.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    kind = env.ref('l10n_ua_hr_salary.accrual_type_teaching_hourly',
                   raise_if_not_found=False)
    if kind and not kind.l10n_ua_vacation_included:
        kind.l10n_ua_vacation_included = True
        _logger.info('TEACH_HOURLY: позначено «ставка включає відпускні» '
                     '(середня для відпусток, #417 Р1)')
