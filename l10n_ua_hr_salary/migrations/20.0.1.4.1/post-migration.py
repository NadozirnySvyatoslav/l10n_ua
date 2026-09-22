"""Надбавки й підсумковий оклад версій — у гривню за курсом.

Обидва поля збережені й обидва рахуються від окладу, тож у базах із
валютним окладом лежать неконвертовані числа: надбавка «10% від окладу»
при 1000 USD — це 100 грн, а `total_wage` додає валютний оклад до
гривневих надбавок. Нові формули самі їх не зачеплять — спрацюють лише
коли зміниться котрась із залежностей.

Скрипт живе в модулі зарплати, хоча править дані `l10n_ua_hr_contract`, і
це не недогляд: валюту окладу оголошує саме цей модуль, а contract
вантажиться раніше за нього. У «своїй» теці міграція побачила б
`hr.version` без поля валюти, узяла б оклад за гривневий і переписала
поля тими самими числами — тихо й із бадьорим звітом у лозі.

Окрема версія 20.0.1.4.1, а не доповнення до 20.0.1.4.0: та вже
випущена, і бази, які на неї оновились, повторно її не виконують.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    Allowance = env['hr.version.allowance']
    allowances = Allowance.search([
        ('calculation_method', '=', 'percent_salary')])
    if allowances:
        env.add_to_compute(Allowance._fields['calculated_amount'], allowances)
        allowances.flush_recordset(['calculated_amount'])
        _logger.info(
            'l10n_ua_hr_salary 20.0.1.4.1: перераховано %s надбавок '
            '«відсоток від окладу»', len(allowances))

    Version = env['hr.version']
    versions = Version.search([('wage', '>', 0)])
    if versions:
        env.add_to_compute(Version._fields['total_wage'], versions)
        versions.flush_recordset(['total_wage'])
        _logger.info(
            'l10n_ua_hr_salary 20.0.1.4.1: перераховано total_wage у %s '
            'версіях договорів', len(versions))
