"""TEACH_HOURLY більше не входить у середню для відпусток (#417, Р1).

Ставки погодинної оплати ПКМУ № 1078 уже включають оплату за дні відпустки
(примітка 4 до ставок), тож у середній для відпускних ці години рахувались би
вдруге. Запис виду нарахування — noupdate, тому прапорець у наявних базах
знімаємо тут. ПДФО, ВЗ, ЄСВ і база лікарняних не змінюються.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE hr_accrual_type t
           SET is_basic_salary = FALSE
          FROM ir_model_data d
         WHERE d.module = 'l10n_ua_hr_salary'
           AND d.name = 'accrual_type_teaching_hourly'
           AND d.model = 'hr.accrual.type'
           AND d.res_id = t.id
           AND t.is_basic_salary IS TRUE
    """)
    if cr.rowcount:
        _logger.info('TEACH_HOURLY: is_basic_salary знято (середня для відпусток, #417 Р1)')
