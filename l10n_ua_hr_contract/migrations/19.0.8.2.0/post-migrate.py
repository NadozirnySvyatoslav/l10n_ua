"""Merge the three workplace flags into `employment_type_ua`.

`is_main_workplace`, `is_part_time` and `part_time_type` described one thing
between them — whether this employment is the person's primary job or
secondary employment — and could contradict each other while doing it. They
are replaced by a single Selection, and their values are carried over here.

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

VERSION = '19.0.8.2.0'


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s)", (table, column))
    return cr.fetchone()[0]


def migrate(cr, version):
    if not version:
        return

    missing = [name for name in ('is_main_workplace', 'part_time_type')
               if not _column_exists(cr, 'hr_version', name)]
    if missing:
        _logger.info(
            "l10n_ua_hr_contract %s: hr_version.%s absent, nothing to carry "
            "over", VERSION, ' and hr_version.'.join(missing))
        return

    # Every row already reads 'primary': Odoo fills a newly added required
    # column with the field's default before adding the NOT NULL constraint.
    # Only the secondary employments need correcting.
    cr.execute("""
        UPDATE hr_version
           SET employment_type_ua = CASE
                   WHEN part_time_type IN ('internal', 'external')
                       THEN part_time_type
                   ELSE 'external'
               END
         WHERE is_main_workplace IS NOT TRUE
    """)
    moved = cr.rowcount

    # A secondary employment whose type was never filled in. It could not be:
    # the old form only showed the type once the unrelated "part-time work"
    # checkbox was ticked. External is the common case and the safe guess —
    # internal secondary employment is registered by an order the HR officer
    # cannot forget — but the rows are named so the guess can be reviewed.
    cr.execute("""
        SELECT id FROM hr_version
         WHERE is_main_workplace IS NOT TRUE
           AND (part_time_type IS NULL
                OR part_time_type NOT IN ('internal', 'external'))
    """)
    guessed = [row[0] for row in cr.fetchall()]
    if guessed:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s versions were not a main workplace but "
            "carried no secondary employment type; read as external (ids: %s)",
            VERSION, len(guessed), guessed[:50])

    # The mirror image: a main workplace that also carried a secondary
    # employment type. One of the two statements was wrong, and the main
    # workplace flag is the one the HR officer actually maintained, so it wins
    # and the type is dropped. Named for the same reason.
    cr.execute("""
        SELECT id FROM hr_version
         WHERE is_main_workplace IS TRUE
           AND part_time_type IN ('internal', 'external')
    """)
    contradictory = [row[0] for row in cr.fetchall()]
    if contradictory:
        _logger.warning(
            "l10n_ua_hr_contract %s: %s versions were flagged as a main "
            "workplace and as secondary employment at the same time; read as "
            "primary, the secondary type was dropped (ids: %s)",
            VERSION, len(contradictory), contradictory[:50])

    _logger.info(
        "l10n_ua_hr_contract %s: %s versions carried over to secondary "
        "employment, the rest read as a primary job", VERSION, moved)
