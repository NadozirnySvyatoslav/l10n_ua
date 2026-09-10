"""Date the cancellations that were never dated.

Occupancy is counted on the date of the staffing line now, so a cancelled
combination has to say *when* it stopped. One carrying no `date_to` can say
nothing, and `hr.staffing.table._occupancy_from_combinings` therefore drops it
from every period alike — including the years it genuinely ran. `action_cancel`
stamps the date from now on; records cancelled before that change carry none,
and no dependency will ever come back for them.

The date is recovered from what was already written down, never guessed. First
the allowance: the old `action_cancel` closed it on the day of the
cancellation, so that column *is* the record of when the surcharge — and with
it the post — stopped. The cancellation order's own date is the fallback, for
combinations that never had an allowance to close.

That order matters twice. Taking the allowance's date means the two agree
afterwards, and nothing about the surcharge has to move; where the order was
dated earlier than the day somebody got round to the button, the difference was
paid, and a script restoring staffing history is no place to rewrite money that
has already gone out. Hence the raw UPDATE below rather than a write through
the ORM: `write` would pull `_sync_allowance` along with it and re-derive every
allowance it touched.

What neither source can date is left alone and counted in the log. There is no
telling when such a combination stopped, and inventing a day would put a staff
unit back into a period on a guess.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Combining = env['hr.job.combining']
    combinings = Combining.search([
        ('state', '=', 'cancelled'), ('date_to', '=', False)])
    if not combinings:
        return

    dated = []
    undated = Combining.browse()
    for combining in combinings:
        ends_on = (combining.allowance_id.date_to
                   or combining.cancellation_order_date)
        # An end before the start is not an end date at all: `_check_dates`
        # refuses it, and rightly — such a combination never ran, and the count
        # is right to drop it.
        if not ends_on or (combining.date_from
                           and ends_on < combining.date_from):
            undated |= combining
            continue
        dated.append((ends_on, combining.id))

    if dated:
        cr.executemany(
            "UPDATE hr_job_combining SET date_to = %s WHERE id = %s", dated)
        env.invalidate_all()
        # The positions the dated combinations occupy have to be counted
        # again: the SQL above went round the ORM, so nothing has told the
        # staffing table that these periods now have an end.
        env['hr.staffing.table']._recompute_occupancy(
            Combining.browse(id for _ends_on, id in dated)._staffing_positions())
        env.flush_all()

    _logger.info(
        'l10n_ua_hr_contract: dated %s cancelled job combinings, %s left '
        'without an end date and outside the occupancy count',
        len(dated), len(undated))
