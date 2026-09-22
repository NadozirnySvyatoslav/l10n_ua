"""Give every company its own set of UA working schedules.

Until this version the ten schedules from the data file were created without
a company_id and therefore inherited it from the field default, i.e. whichever
company happened to be active while the module was installed. One record per
database meant the schedule belonged to exactly one company while employees of
the other ones pointed at a foreign schedule: their "Working Hours" field
showed another company, and the obvious fix - changing company_id on the
schedule itself - switched it for everyone at once.

Here those ten records become templates (no company, archived), every company
gets its own copy of every schedule, and all references are repointed to the
copy of their own company.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

def _calendar_references(cr):
    """Discover every (table, column) that points at a schedule per company.

    Built from the live foreign keys rather than a hard-coded list: which
    tables exist depends on the installed modules, and missing one of them
    leaves records pointing at an archived template - a leave sitting on the
    template is invisible to _leave_intervals_batch, which filters by
    calendar_id, so it silently stops being subtracted from the working time.

    Only tables carrying a company_id qualify - that column is what tells us
    which copy the row belongs to. This excludes resource_calendar_attendance
    (the working hour lines belong to the calendar itself) and res_company,
    which is handled separately.

    resource_calendar_leaves is excluded for the same reason as the attendance
    lines, even though it does carry a company_id: that column is a stored
    compute over calendar_id.company_id (addons/resource), so the rows belong
    to the calendar rather than to a company of their own, and the copies
    already carry their own. Repointing them moved the original onto the same
    copy the duplicate sits on, leaving the company with the public holiday
    twice - which core's own overlap constraint forbids.
    """
    cr.execute("""
        SELECT tc.table_name, kcu.column_name
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
          JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
         WHERE tc.constraint_type = 'FOREIGN KEY'
           AND ccu.table_name = 'resource_calendar'
           AND tc.table_name NOT IN ('resource_calendar',
                                     'resource_calendar_leaves')
           AND EXISTS (SELECT 1 FROM information_schema.columns c
                        WHERE c.table_name = tc.table_name
                          AND c.column_name = 'company_id')
         ORDER BY tc.table_name
    """)
    return cr.fetchall()


def _demote_records_to_templates(cr):
    """Turn the data file records into templates.

    Done in plain SQL: attendance_ids is a stored compute depending on
    company_id (addons/resource/models/resource_calendar.py), and even though
    it does not trigger on saved records (there _origin == self), relying on
    that detail inside a migration that rewrites live data is not worth it -
    an ORM write could wipe the working hour lines.
    """
    cr.execute("""
        UPDATE resource_calendar SET company_id = NULL, active = false
         WHERE id IN (SELECT res_id FROM ir_model_data
                       WHERE module = 'l10n_ua_hr_contract'
                         AND model = 'resource.calendar')
           AND (company_id IS NOT NULL OR active)
    """)
    return cr.rowcount


def _repoint_by_ua_code(cr, table, column):
    """Point references at a foreign (or template) schedule to the own copy."""
    cr.execute("""
        UPDATE {table} t SET {column} = own.id
          FROM resource_calendar cur
          JOIN resource_calendar own ON own.ua_code = cur.ua_code
         WHERE cur.id = t.{column}
           AND cur.ua_code IS NOT NULL
           AND own.company_id = t.company_id
           AND own.active
           AND (cur.company_id IS NULL OR cur.company_id <> t.company_id)
    """.format(table=table, column=column))
    return cr.rowcount


def _repoint_company_defaults(cr):
    """res_company.resource_calendar_id must not point at a foreign schedule."""
    cr.execute("""
        UPDATE res_company c SET resource_calendar_id = own.id
          FROM resource_calendar cur
          JOIN resource_calendar own ON own.ua_code = cur.ua_code
         WHERE cur.id = c.resource_calendar_id
           AND cur.ua_code IS NOT NULL
           AND own.company_id = c.id
           AND own.active
           AND (cur.company_id IS NULL OR cur.company_id <> c.id)
    """)
    return cr.rowcount


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    demoted = _demote_records_to_templates(cr)
    env['resource.calendar'].invalidate_model()
    _logger.info(
        "l10n_ua_hr_contract 20.0.6.0.0: demoted %s schedules to templates",
        demoted)

    companies = env['res.company'].search([])
    companies._l10n_ua_create_resource_calendars()
    # The copies are created through the ORM - flush them to the database
    # before the raw UPDATE statements below.
    env.flush_all()
    _logger.info(
        "l10n_ua_hr_contract 20.0.6.0.0: distributed the schedules to %s "
        "companies", len(companies))

    references = _calendar_references(cr)
    moved = 0
    for table, column in references:
        moved += _repoint_by_ua_code(cr, table, column)
    moved += _repoint_company_defaults(cr)
    env.invalidate_all()
    _logger.info(
        "l10n_ua_hr_contract 20.0.6.0.0: repointed %s references to the "
        "schedule of their own company", moved)

    # Sanity check, counted apart because the two leftovers mean different
    # things: a row on another company's schedule is a pre-existing misfiling
    # this migration deliberately does not touch, while a row left on an
    # archived template is damage this migration itself would have caused.
    for table, column in references:
        cr.execute("""
            SELECT count(*) FILTER (WHERE NOT rc.active
                                      AND rc.company_id IS NULL),
                   count(*) FILTER (WHERE rc.active
                                      AND rc.company_id IS DISTINCT FROM
                                          t.company_id)
              FROM {table} t
              JOIN resource_calendar rc ON rc.id = t.{column}
        """.format(table=table, column=column))
        # Archived AND company-less is what a template looks like; a
        # calendar the user archived themselves keeps its company and is none
        # of this migration's business.
        on_template, misfiled = cr.fetchone()
        if on_template:
            # Nothing to pick from: a row with no company of its own has no
            # copy to be moved to. Reported rather than guessed at.
            _logger.warning(
                "l10n_ua_hr_contract 20.0.6.0.0: %s has %s rows left on an "
                "archived schedule template - they carry no company_id, so "
                "there is no copy to move them to. Assign a schedule of the "
                "right company by hand.", table, on_template)
        if misfiled:
            _logger.warning(
                "l10n_ua_hr_contract 20.0.6.0.0: %s has %s rows pointing at a "
                "schedule of another company. They carry no ua_code, were "
                "already like that before this migration and are left "
                "untouched on purpose: a custom schedule shared across "
                "companies can be a deliberate setup, and there is no "
                "counterpart to match it against.", table, misfiled)

    # Tables without a company_id cannot be repointed automatically: there is
    # no own copy to pick. hr.payroll.structure.type is the one such pointer in
    # the HR stack, so it is only reported.
    cr.execute("""
        SELECT EXISTS (SELECT FROM information_schema.tables
                        WHERE table_name = 'hr_payroll_structure_type')
    """)
    if cr.fetchone()[0]:
        cr.execute("""
            SELECT count(*) FROM hr_payroll_structure_type s
              JOIN resource_calendar rc ON rc.id = s.default_resource_calendar_id
             WHERE NOT rc.active
        """)
        left = cr.fetchone()[0]
        if left:
            _logger.warning(
                "l10n_ua_hr_contract 20.0.6.0.0: %s salary structure types "
                "still default to an archived schedule template - pick a "
                "company schedule manually", left)
