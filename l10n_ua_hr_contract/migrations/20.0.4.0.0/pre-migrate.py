"""Guard the removal of hr.work.schedule (#213, phase 2).

Phase 1 (20.0.3.0.0) mapped every `hr.version.work_schedule_ua_id` onto the
native `resource_calendar_id`. Phase 2 deletes the UA models, so this upgrade
must not be the one that also has to perform that mapping: the module code is
already gone by the time 20.0.3.0.0/post-migrate runs, and the versions would
silently fall back to the company default calendar — a different weekly norm,
hence different leave entitlement and payroll.

A database that is behind therefore has to make the two steps separately.
"""

import logging

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PHASE_1_VERSION = (19, 0, 3, 0, 0)


def _table_exists(cr, table):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables "
        "WHERE table_name = %s)", (table,))
    return cr.fetchone()[0]


def _parsed(version):
    """Version tuple of a module version string, without its Odoo prefix."""
    parts = []
    for chunk in (version or '').split('.'):
        try:
            parts.append(int(chunk))
        except ValueError:
            return ()
    return tuple(parts)


def migrate(cr, version):
    if not version:
        return

    if not _table_exists(cr, 'hr_work_schedule'):
        # Never had the UA models (clean install of an earlier phase-2 build).
        return

    installed = _parsed(version)
    if installed and installed < PHASE_1_VERSION:
        raise UserError(
            "l10n_ua_hr_contract %s cannot be upgraded straight to 20.0.4.0.0.\n\n"
            "20.0.3.0.0 moves the Ukrainian work schedules onto the native "
            "resource.calendar; 20.0.4.0.0 deletes them. Run the upgrade in "
            "two steps — install 20.0.3.0.0 first, check the migration log for "
            "versions it skipped, then upgrade to 20.0.4.0.0." % version
        )

    cr.execute("""
        SELECT COUNT(*) FROM hr_version
        WHERE work_schedule_ua_id IS NOT NULL
          AND resource_calendar_id IS NULL
    """)
    unmapped = cr.fetchone()[0]
    if unmapped:
        raise UserError(
            "l10n_ua_hr_contract 20.0.4.0.0: %s contract versions still carry "
            "a Ukrainian work schedule but no working hours calendar. Removing "
            "the schedules now would leave them without a working time norm. "
            "Re-run the 20.0.3.0.0 migration or set resource_calendar_id on "
            "those versions first." % unmapped
        )

    _logger.info(
        "l10n_ua_hr_contract 20.0.4.0.0: every version carrying a legacy work "
        "schedule has a working hours calendar, removal can proceed")
