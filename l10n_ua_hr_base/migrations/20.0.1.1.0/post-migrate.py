"""Migrate legacy employee addresses onto the Odoo 19 private_* address.

This script runs on a large and varied installed base, so it makes no
assumptions beyond "the module is being upgraded": every legacy column is
probed before use, every statement is idempotent, and no statement can
overwrite an address a customer already keeps in the native fields.

The one rule the whole script is built around: **nothing is ever lost.**
registration_same_as_actual is only left enabled where mirroring the private
address onto the registration block cannot destroy a differing value; wherever
the two addresses actually disagree the flag is cleared and both survive
side by side, for the HR officer to reconcile.
"""

import logging

from odoo.tools.sql import column_exists, table_exists

_logger = logging.getLogger(__name__)

# Legacy registration_address / actual_address were free-form Text, so they may
# carry line breaks that a single-line Char must not inherit.
_FLATTEN = r"btrim(regexp_replace({}, E'\\s*\\n\\s*', ', ', 'g'))"

# hr_employee.version_id is a non-stored compute in Odoo 19 and has no column,
# so the version an employee's private_* address resolves to is reproduced here:
# current_version_id, else the newest version that is not in the future, else
# the oldest one (hr.version._order = 'date_version').
_CURRENT_VERSION = """
    WITH current_version AS (
        SELECT e.id AS employee_id,
               COALESCE(e.current_version_id, (
                   SELECT v.id
                     FROM hr_version v
                    WHERE v.employee_id = e.id
                    ORDER BY v.active DESC,
                             (v.date_version <= CURRENT_DATE) DESC,
                             CASE WHEN v.date_version <= CURRENT_DATE
                                  THEN v.date_version END DESC,
                             v.date_version ASC, v.id ASC
                    LIMIT 1
               )) AS version_id
          FROM hr_employee e
    )
"""

# Columns the new address block cannot work without. Their absence means the
# module's own _auto_init did not complete, so there is nothing sane to do.
_REQUIRED_EMPLOYEE_COLUMNS = (
    'registration_same_as_actual', 'registration_street', 'registration_street2',
    'registration_city', 'registration_zip', 'registration_region_id',
    'current_version_id',
)
_REQUIRED_VERSION_COLUMNS = (
    'private_street', 'private_street2', 'private_city', 'private_zip',
    'private_state_id', 'employee_id', 'date_version',
)


def _text_conflicts(private_column, registration_column):
    """SQL: the two text columns hold different, both non-empty, values.

    An empty side is never a conflict — there is nothing to lose by mirroring
    onto it, or nothing to mirror from it.
    """
    return """(COALESCE({priv}, '') <> ''
               AND COALESCE({reg}, '') <> ''
               AND {priv} <> {reg})""".format(priv=private_column, reg=registration_column)


def _missing(cr, table, columns):
    return [name for name in columns if not column_exists(cr, table, name)]


def migrate(cr, version):
    _logger.info("l10n_ua_hr_base 20.0.1.1.0: starting employee address migration.")

    if not table_exists(cr, 'hr_version'):
        _logger.error(
            "l10n_ua_hr_base 20.0.1.1.0: table hr_version is missing — this "
            "database does not look like Odoo 19 hr. Skipping address migration.")
        return

    missing = (_missing(cr, 'hr_employee', _REQUIRED_EMPLOYEE_COLUMNS)
               + _missing(cr, 'hr_version', _REQUIRED_VERSION_COLUMNS))
    if missing:
        _logger.error(
            "l10n_ua_hr_base 20.0.1.1.0: required columns are missing (%s). "
            "Skipping address migration; re-run the module upgrade.",
            ', '.join(missing))
        return

    has_legacy_flag = column_exists(cr, 'hr_employee', 'actual_same_as_registration')
    has_legacy_registration = column_exists(cr, 'hr_employee', 'registration_address')
    has_legacy_actual = column_exists(cr, 'hr_employee', 'actual_address')

    if has_legacy_registration:
        _fill_registration_street_from_legacy_text(cr)

    if has_legacy_flag:
        _carry_over_flag(cr)
        _fill_private_from_registration(cr)
        if has_legacy_actual:
            _fill_private_from_legacy_actual(cr)
    else:
        _logger.info(
            "l10n_ua_hr_base 20.0.1.1.0: no legacy actual_same_as_registration "
            "column; only reconciling the registration block.")

    _reconcile_registration_from_private(cr)
    _assert_consistent(cr)

    _logger.info("l10n_ua_hr_base 20.0.1.1.0: employee address migration completed.")


def _assert_consistent(cr):
    """Post-condition: no mirrored employee is left out of sync.

    Logged rather than raised — an upgrade that already moved the data must not
    be rolled back over a reporting detail — but a non-zero count means the
    registration block and the current version disagree and needs looking at.
    """
    cr.execute(_CURRENT_VERSION + """
        SELECT count(*)
          FROM current_version cv
          JOIN hr_employee e ON e.id = cv.employee_id
          JOIN hr_version v ON v.id = cv.version_id
         WHERE e.registration_same_as_actual = TRUE
           AND (e.registration_street IS DISTINCT FROM v.private_street
             OR e.registration_street2 IS DISTINCT FROM v.private_street2
             OR e.registration_city IS DISTINCT FROM v.private_city
             OR e.registration_zip IS DISTINCT FROM v.private_zip
             OR e.registration_region_id IS DISTINCT FROM v.private_state_id)
    """)
    out_of_sync = cr.fetchone()[0]
    if out_of_sync:
        _logger.error(
            "l10n_ua_hr_base 20.0.1.1.0: %s mirrored employees are still out of "
            "sync with their current version after the migration.", out_of_sync)
    else:
        _logger.info(
            "l10n_ua_hr_base 20.0.1.1.0: every mirrored employee matches its "
            "current version.")


def _fill_registration_street_from_legacy_text(cr):
    """Legacy free-form registration_address -> structured registration_street.

    Only fills an empty street, so re-running the upgrade never re-flattens an
    address the HR officer has since split into street / street2 by hand.
    """
    cr.execute("""
        UPDATE hr_employee
           SET registration_street = {flattened}
         WHERE COALESCE(registration_street, '') = ''
           AND COALESCE(registration_address, '') != ''
    """.format(flattened=_FLATTEN.format('registration_address')))
    _logger.info(
        "l10n_ua_hr_base 20.0.1.1.0: %s legacy registration_address values "
        "moved into registration_street.", cr.rowcount)


def _carry_over_flag(cr):
    """Carry the legacy flag over, but only where mirroring is lossless.

    The legacy flag only ever meant "both addresses are the same", so the
    inverted name does not change its meaning. It is enabled only where the
    private and registration addresses do not contradict each other: turning it
    on elsewhere would make the reconciliation step below overwrite one of two
    genuinely different addresses the customer has been maintaining, so those
    employees are left with the flag off and both addresses intact.

    An already-enabled flag is never turned off here — the reconciliation step
    is what such a record needs, not a downgrade.
    """
    cr.execute(_CURRENT_VERSION + """
        UPDATE hr_employee e
           SET registration_same_as_actual = TRUE
          FROM current_version cv
          LEFT JOIN hr_version v ON v.id = cv.version_id
         WHERE cv.employee_id = e.id
           AND COALESCE(e.actual_same_as_registration, FALSE) = TRUE
           AND COALESCE(e.registration_same_as_actual, FALSE) = FALSE
           AND NOT ({street_conflict})
           AND NOT ({city_conflict})
           AND NOT ({zip_conflict})
           AND NOT (v.private_state_id IS NOT NULL
                    AND e.registration_region_id IS NOT NULL
                    AND v.private_state_id <> e.registration_region_id)
    """.format(
        street_conflict=_text_conflicts('v.private_street', 'e.registration_street'),
        city_conflict=_text_conflicts('v.private_city', 'e.registration_city'),
        zip_conflict=_text_conflicts('v.private_zip', 'e.registration_zip'),
    ))
    mirrored = cr.rowcount

    # Everything the legacy data does not vouch for stays False, including the
    # rows where the two addresses diverge and both must be preserved.
    cr.execute("""
        SELECT count(*)
          FROM hr_employee
         WHERE COALESCE(actual_same_as_registration, FALSE) = TRUE
           AND COALESCE(registration_same_as_actual, FALSE) = FALSE
    """)
    kept_separate = cr.fetchone()[0]

    _logger.info(
        "l10n_ua_hr_base 20.0.1.1.0: %s employees keep the addresses mirrored; "
        "%s had a private address differing from their registration address and "
        "keep both (flag cleared, please review).", mirrored, kept_separate)


def _fill_private_from_registration(cr):
    """Seed an empty native address from the legacy registration address.

    Runs for mirrored employees only, and every column is filled through
    COALESCE, so a value the customer already has in private_* always wins.
    """
    cr.execute(_CURRENT_VERSION + """
        UPDATE hr_version v
           SET private_street = COALESCE(NULLIF(v.private_street, ''), NULLIF(e.registration_street, '')),
               private_street2 = COALESCE(NULLIF(v.private_street2, ''), NULLIF(e.registration_street2, '')),
               private_city = COALESCE(NULLIF(v.private_city, ''), NULLIF(e.registration_city, '')),
               private_zip = COALESCE(NULLIF(v.private_zip, ''), NULLIF(e.registration_zip, '')),
               private_state_id = COALESCE(v.private_state_id, e.registration_region_id)
          FROM current_version cv
          JOIN hr_employee e ON e.id = cv.employee_id
         WHERE v.id = cv.version_id
           AND e.registration_same_as_actual = TRUE
           AND (COALESCE(v.private_street, '') = '' AND COALESCE(e.registration_street, '') <> ''
             OR COALESCE(v.private_street2, '') = '' AND COALESCE(e.registration_street2, '') <> ''
             OR COALESCE(v.private_city, '') = '' AND COALESCE(e.registration_city, '') <> ''
             OR COALESCE(v.private_zip, '') = '' AND COALESCE(e.registration_zip, '') <> ''
             OR v.private_state_id IS NULL AND e.registration_region_id IS NOT NULL)
    """)
    _logger.info(
        "l10n_ua_hr_base 20.0.1.1.0: %s current versions seeded from the "
        "registration address.", cr.rowcount)


def _fill_private_from_legacy_actual(cr):
    """Seed an empty native street from the legacy actual_address text.

    For employees whose two addresses differed, actual_address is what the
    native private block is supposed to hold from now on.
    """
    cr.execute(_CURRENT_VERSION + """
        UPDATE hr_version v
           SET private_street = {flattened}
          FROM current_version cv
          JOIN hr_employee e ON e.id = cv.employee_id
         WHERE v.id = cv.version_id
           AND COALESCE(e.registration_same_as_actual, FALSE) = FALSE
           AND COALESCE(e.actual_address, '') <> ''
           AND COALESCE(v.private_street, '') = ''
    """.format(flattened=_FLATTEN.format('e.actual_address')))
    seeded = cr.rowcount

    # Employees who already keep a native address are left alone — overwriting
    # a maintained value with legacy text would be the worse trade. Report them
    # so support can tell "nothing to do" from "silently dropped".
    cr.execute(_CURRENT_VERSION + """
        SELECT count(*)
          FROM current_version cv
          JOIN hr_employee e ON e.id = cv.employee_id
          JOIN hr_version v ON v.id = cv.version_id
         WHERE COALESCE(e.registration_same_as_actual, FALSE) = FALSE
           AND COALESCE(e.actual_address, '') <> ''
           AND COALESCE(v.private_street, '') <> ''
           AND {flattened} <> v.private_street
    """.format(flattened=_FLATTEN.format('e.actual_address')))
    superseded = cr.fetchone()[0]

    _logger.info(
        "l10n_ua_hr_base 20.0.1.1.0: %s current versions seeded from the legacy "
        "actual_address; %s kept their existing native address instead.",
        seeded, superseded)


def _reconcile_registration_from_private(cr):
    """Bring the registration block in line with the current version.

    Runs unconditionally: a database that already lost the legacy columns, or
    one that ran an earlier build of this script and picked an arbitrary
    version, still ends up consistent with what the form shows.
    """
    cr.execute(_CURRENT_VERSION + """
        UPDATE hr_employee e
           SET registration_street = v.private_street,
               registration_street2 = v.private_street2,
               registration_city = v.private_city,
               registration_zip = v.private_zip,
               registration_region_id = v.private_state_id
          FROM current_version cv
          JOIN hr_version v ON v.id = cv.version_id
         WHERE cv.employee_id = e.id
           AND e.registration_same_as_actual = TRUE
           AND (e.registration_street IS DISTINCT FROM v.private_street
             OR e.registration_street2 IS DISTINCT FROM v.private_street2
             OR e.registration_city IS DISTINCT FROM v.private_city
             OR e.registration_zip IS DISTINCT FROM v.private_zip
             OR e.registration_region_id IS DISTINCT FROM v.private_state_id)
    """)
    _logger.info(
        "l10n_ua_hr_base 20.0.1.1.0: %s registration blocks reconciled with the "
        "current version.", cr.rowcount)
