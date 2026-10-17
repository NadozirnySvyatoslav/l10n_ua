"""The days of a timesheet now keep the hours the working schedule plans for
them, next to the hours worked. The days generated before have none; they get
the plan the generator gives today, read from the current versions, time off
and holidays. Only the norm is written: the hours, the codes and the
scheduled flag stay as entered. Confirmed and approved timesheets are filled
too — the norm is for information and pays nothing.
"""

import logging
from collections import defaultdict

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['hr.timesheet.line'].search([('day_ids', '!=', False)])
    by_norm = defaultdict(list)
    for line in lines:
        plan = {day['date']: day['hours'] for day in line._l10n_ua_plan_days()}
        for day in line.day_ids:
            norm = plan.get(day.date, 0.0)
            if norm:
                by_norm[norm].append(day.id)
    for norm, ids in by_norm.items():
        env['hr.timesheet.day'].browse(ids).write({'norm_hours': norm})
    _logger.info('Filled the norm hours of %d timesheet lines.', len(lines))
