"""Параметри на 2027 рік (#351).

Період 2027 року компаніям додає `_seed_company_parameters` під час оновлення
модуля. Тут лише закриваємо відкритий 2026 рік (date_to = 31.12.2026): підбір
і так бере найсвіжіший запис, але відкритий період у списку параметрів
вводить в оману. Запис, який користувач уже закрив іншою датою, не чіпаємо.
"""
import logging
from datetime import date

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    open_2026 = env['hr.psp.parameters'].with_context(active_test=False).search([
        ('date_from', '=', date(2026, 1, 1)), ('date_to', '=', False),
    ])
    open_2026.write({'date_to': date(2026, 12, 31)})
    _logger.info('l10n_ua_hr_salary 19.0.1.7.2: закрито 2026 рік у %s записах параметрів',
                 len(open_2026))
