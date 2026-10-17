"""Bring leaves entered before the duration followed the public holiday list
in step with it (#344).

A leave counted its public holidays once, when its dates were saved; a holiday
added, moved or removed afterwards never reached it. Every leave that is not
refused or cancelled is recounted once against the list as it stands now, and
each one whose duration moves gets a chatter note with the old and the new
figures, so the accountant can check the list. The same pass applies the way
holidays are now read — those of the employee's company or of none, on their
day in the company's time zone — which the payslip already uses.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

BATCH = 500


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    # The chatter notes are a one-off record for the accountant: written in
    # Ukrainian when the language is installed.
    if env['res.lang']._lang_get('uk_UA'):
        env = env(context={'lang': 'uk_UA'})
    Leave = env['hr.leave'].with_context(active_test=False)
    leaves = Leave.search([
        ('state', 'not in', ['refuse', 'cancel']),
        ('request_date_from', '!=', False),
        ('request_date_to', '!=', False),
    ], order='request_date_from, id')
    changed = Leave.browse()
    for start in range(0, len(leaves), BATCH):
        batch = leaves[start:start + BATCH]
        changed |= batch._l10n_ua_refresh_holiday_durations(
            reason=Leave._l10n_ua_upgrade_recount_reason())
    _logger.info('Leaves recounted against public holidays: %s, changed: %s',
                 len(leaves), len(changed))
    if changed:
        _logger.warning('Leaves whose duration changed (see their chatter): %s',
                        ', '.join(str(i) for i in changed.ids))
