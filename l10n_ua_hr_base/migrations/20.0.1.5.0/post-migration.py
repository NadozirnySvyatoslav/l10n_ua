"""Recount staff-unit occupancy against the period of each line.

`hr.staffing.table.filled_units` is stored, so the database holds figures
produced by the old rule: how many units of the position are filled *today*.
Since #300 a position keeps a history of approved lines, and that one figure
landed on all of them alike — the 2023 line reported the occupancy of the
current day.

The new rule counts occupancy on the date of the line itself. What changed is
the meaning of the stored field, not merely the way it is derived, so without
a forced recount the historical lines would keep the inherited figure for
ever: no dependency reaches them any more, precisely because they are
historical.

`vacant_units` is queued alongside it — see `_mark_occupancy_dirty`.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Staffing = env['hr.staffing.table']
    lines = Staffing.search([])
    if not lines:
        return
    lines._mark_occupancy_dirty()
    env.flush_all()
    _logger.info(
        'l10n_ua_hr_base: recomputed occupancy on %s staffing lines',
        len(lines))
