"""Migration — hire_date becomes derived from the native contract versions.

`hr.employee.hire_date` is now computed (store=True, readonly=False) from
`hr.version.contract_date_start` through the core helper
`_get_ua_first_contract_date()`. The database column already exists, so Odoo
does NOT recompute it on upgrade by itself — this migration does it
explicitly.

Three steps:

1. Log divergences BEFORE anything is overwritten: wherever HR kept one date
   in hire_date while the contract version carries another, the version (the
   native field) wins from now on. The log gives HR the list of records to
   review.
2. Backfill the contract versions of employees that carry a hire_date but no
   contract dates at all (legacy import). After this the employee form no
   longer needs a writable hire_date: every record is backed by a version.
3. Recompute hire_date for every employee.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _log_divergences(employees):
    """Report employees whose manual hire_date differs from the versions."""
    diverged = 0
    for employee in employees:
        native = employee.sudo()._get_ua_first_contract_date()
        if native and employee.hire_date and native != employee.hire_date:
            diverged += 1
            _logger.warning(
                "hire_date %s (id=%s): %s -> %s (from contract versions)",
                employee.display_name, employee.id,
                employee.hire_date, native,
            )
    return diverged


def _backfill_contract_dates(employees):
    """Move a legacy hire_date into the employee's contract versions.

    Only employees whose versions carry no contract_date_start at all are
    touched — where native data exists it already wins, and overwriting it
    from a stale manual field would lose information.

    The date goes to EVERY version of the employee, not just the earliest.
    Core treats contract_date_start as a property of the contract period that
    is replicated across the versions belonging to it (see `create_version`),
    and `hr.version.write` refuses to touch contract dates on a set of
    versions holding different values — leaving some versions at NULL would
    make `_apply_dismissal`, which closes all versions in one write, fail with
    "Cannot modify multiple versions contract dates with different contracts
    at once".

    A departure date is carried over to contract_date_end in the same write:
    once versions carry a contract period, `_was_employed_on` decides purely
    from them and stops looking at the employee's departure_date, so a
    dismissed employee whose versions stayed open would resurface in the
    employee list report as still employed. The DB constraint
    `contract_date_end IS NULL OR contract_date_start IS NOT NULL` also
    requires both to be written together.

    `sync_contract_dates=True` makes core write the values verbatim instead of
    forcing `date_version` onto single-version employees or propagating dates
    across contract periods — this migration knows exactly what it wants to
    set, and a forced date_version would collide with the unique
    (employee_id, date_version) index when an archived version exists.
    """
    backfilled = 0
    for employee in employees:
        if not employee.hire_date:
            continue
        if employee.sudo()._get_ua_first_contract_date():
            continue
        versions = employee.with_context(active_test=False).version_ids
        if not versions:
            continue
        vals = {'contract_date_start': employee.hire_date}
        departure = employee.departure_date
        if departure and departure >= employee.hire_date:
            vals['contract_date_end'] = departure
        versions.sudo().with_context(sync_contract_dates=True).write(vals)
        backfilled += 1
    return backfilled

def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Employee = env['hr.employee'].with_context(active_test=False)
    employees = Employee.search([])

    diverged = _log_divergences(employees)
    backfilled = _backfill_contract_dates(employees)

    env.add_to_compute(Employee._fields['hire_date'], employees)
    env.flush_all()

    _logger.info(
        "hire_date: %d employees processed, %d divergences, "
        "%d legacy hire dates moved into contract versions",
        len(employees), diverged, backfilled,
    )
