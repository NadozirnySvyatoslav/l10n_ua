"""Merge the three workplace flags into `employment_type_ua`.

`is_main_workplace`, `is_part_time` and `part_time_type` described one thing
between them — whether this employment is the person's primary job or
secondary employment — and could contradict each other while doing it. They
are replaced by a single Selection, and their values are carried over here.

Only a deliberate secondary employment is carried over; everything else stays
on the column default, `primary`. That asymmetry is not caution for its own
sake — `is_main_workplace = FALSE` is not evidence of anything:

    20.0.2.0.0/pre-migrate.py created the column with
    `ALTER TABLE hr_version ADD COLUMN is_main_workplace BOOLEAN DEFAULT FALSE`,
    so every row that existed at that upgrade was stamped FALSE. Its
    post-migrate then set the real value on employees who had an *open*
    `hr_contract_ua`, and only on their current version. Everyone else — past
    versions, employees without a UA contract, employees whose contract was
    closed — kept the FALSE nobody chose. And because the column was created
    by SQL rather than by the ORM, the field's `default=True` never reached
    those rows either.

Reading FALSE as secondary employment would therefore turn whole payroll
histories into external secondary jobs. So the two signals that are actually
deliberate decide instead:

  1. `part_time_type` was NULL by default and is only ever filled in by hand
     (or from a hand-filled UA contract) — it is taken at face value, even
     where `is_main_workplace` is TRUE, because TRUE is what every new version
     gets for free from the field default while nobody picks "Internal
     secondary job" by accident.
  2. `is_part_time = TRUE` together with a cleared main-workplace flag, but no
     type, is NOT carried over. The cleared flag may be nothing but the
     20.0.2.0.0 stamp, and part-time work at the main workplace is not
     secondary employment; guessing `external` would change the person for
     payroll. These rows stay primary and every id is logged for review.

Everything else is left primary, and the count is logged so it can be
reviewed. To see what this will do before upgrading, run on a copy:

    SELECT count(*) FILTER (WHERE part_time_type IN ('internal','external')) AS explicit,
           count(*) FILTER (WHERE part_time_type IS NULL
                              AND is_part_time IS TRUE
                              AND is_main_workplace IS NOT TRUE)            AS guessed,
           count(*) FILTER (WHERE part_time_type IS NULL
                              AND is_part_time IS NOT TRUE
                              AND is_main_workplace IS NOT TRUE)            AS left_primary
      FROM hr_version;

This runs in post-migrate, not pre-migrate: the new column already exists by
now, while the three old ones are still there. Odoo drops the columns of
fields a module no longer declares only at the very end of the upgrade, once
every module has been loaded (`ir.model.data._process_end`), so both sides of
the mapping are readable at this point and no snapshot table is needed.

Written in SQL rather than through the ORM on purpose: the field is tracked,
and a write would drop a chatter entry into every employee's record. A data
migration is not an event in someone's working life.
"""
import logging

_logger = logging.getLogger(__name__)

VERSION = '20.0.8.2.0'


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)", (table, column))
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return

    missing = [name for name in
               ('is_main_workplace', 'is_part_time', 'part_time_type')
               if not _column_exists(cr, 'hr_version', name)]
    if missing:
        _logger.info(
            "l10n_ua_hr_contract %s: hr_version.%s absent, nothing to carry "
            "over", VERSION, ' and hr_version.'.join(missing))
        return

    # Every row already reads 'primary': Odoo fills a newly added required
    # column with the field's default before adding the NOT NULL constraint.
    # Only a deliberate secondary employment is moved off it.
    cr.execute("""
        UPDATE hr_version
           SET employment_type_ua = part_time_type
         WHERE part_time_type IN ('internal', 'external')
    """)
    explicit = cr.rowcount

    # Stated as a secondary job and as a main workplace at once. The explicit
    # type wins: a main-workplace flag is what every version gets by default,
    # whereas the type is only ever there because somebody picked it.
    cr.execute("""
        SELECT count(*) FROM hr_version
         WHERE part_time_type IN ('internal', 'external')
           AND is_main_workplace IS TRUE
    """)
    contradictory = cr.fetchone()[0]
    if contradictory:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s versions carried a secondary "
            "employment type while also flagged as a main workplace; the "
            "explicit type was kept", VERSION, contradictory)

    # An explicit type left behind on a version whose part-time box was later
    # cleared. Still carried over — the type is only ever there because
    # somebody picked it — but named, since unticking the box may have been
    # the way the officer meant to end the secondary employment.
    cr.execute("""
        SELECT id FROM hr_version
         WHERE part_time_type IN ('internal', 'external')
           AND is_part_time IS NOT TRUE
      ORDER BY id
    """)
    stale_type = [row[0] for row in cr.fetchall()]
    if stale_type:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s versions carried a secondary "
            "employment type with the part-time box cleared; the type was "
            "carried over, review them by hand (ids: %s)",
            VERSION, len(stale_type), stale_type)

    # Part-time and not a main workplace, but the type was never chosen. Not
    # moved: the cleared flag may be the 20.0.2.0.0 stamp, and part-time work
    # at a main workplace is not secondary employment — reading it as external
    # would change the person for payroll on a guess. Left primary and named
    # in full, so an officer can set the type by hand where it was meant.
    cr.execute("""
        SELECT id FROM hr_version
         WHERE part_time_type IS NULL
           AND is_part_time IS TRUE
           AND is_main_workplace IS NOT TRUE
      ORDER BY id
    """)
    guessed = [row[0] for row in cr.fetchall()]
    if guessed:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s part-time versions were not flagged as "
            "a main workplace but carried no secondary employment type; left "
            "primary, review them by hand (ids: %s)",
            VERSION, len(guessed), guessed)

    # Left primary despite a cleared main-workplace flag. Expected on any
    # database that went through 20.0.2.0.0, which stamped the whole table
    # FALSE — see the module docstring. Counted, not listed: on such a
    # database this is most of the history.
    cr.execute("""
        SELECT count(*) FROM hr_version
         WHERE part_time_type IS NULL
           AND is_part_time IS NOT TRUE
           AND is_main_workplace IS NOT TRUE
    """)
    left_primary = cr.fetchone()[0]
    if left_primary:
        _logger.info(
            "l10n_ua_hr_contract %s: %s versions had no main-workplace flag "
            "and no other sign of secondary employment; read as a primary "
            "job, because that flag was stamped FALSE on every existing row "
            "by 20.0.2.0.0 and carries no information on its own", VERSION,
            left_primary)

    # The history is noise, but a version still in force is not: if its flag
    # was cleared on purpose, this person is now recorded at a primary job
    # where they hold a secondary one. Those are named.
    cr.execute("""
        SELECT id FROM hr_version
         WHERE part_time_type IS NULL
           AND is_part_time IS NOT TRUE
           AND is_main_workplace IS NOT TRUE
           AND active IS TRUE
           AND (contract_date_end IS NULL OR contract_date_end >= CURRENT_DATE)
      ORDER BY id
    """)
    in_force = [row[0] for row in cr.fetchall()]
    if in_force:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s of them are still in force; check "
            "that none is a secondary job (ids: %s)",
            VERSION, len(in_force), in_force)

    _logger.info(
        "l10n_ua_hr_contract %s: %s versions carried over from an explicit "
        "secondary employment type, %s part-time ones left primary for review, "
        "the rest read as a primary job", VERSION, explicit, len(guessed))
