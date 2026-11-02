"""ПСП: позначки «Заява на ПСП» договорів → документи hr.psp.application (#415).

Поле hr.version.psp_application стало обчислюваним від заяв, але стовпець зі
старими значеннями в таблиці лишився — з нього й беремо, кому заява була.
"""
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version or not column_exists(cr, 'hr_version', 'psp_application'):
        return
    cr.execute("SELECT id FROM hr_version WHERE psp_application AND active")
    ids = [row[0] for row in cr.fetchall()]
    if not ids:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    apps = env['hr.psp.application']._create_from_version_flags(
        env['hr.version'].browse(ids).exists())
    _logger.info('ПСП: створено %s заяв із позначок договорів (%s чинних)',
                 len(apps), len(apps.filtered(lambda a: a.state == 'active')))
