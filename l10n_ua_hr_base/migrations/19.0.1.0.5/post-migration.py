"""Migration #98 — побудова 4-рівневої ієрархії hr.kp2010 за ДК 003:2010.

Алгоритм:
1) Видобути всі унікальні префікси з існуючих кодів (digit-only, до крапки).
2) Для кожного префіксу довжини 1/2/3 створити intermediate record, якщо не існує.
3) Заповнити parent_id для ВСІХ записів (включно з дублікатами) — посилання на найдовший existing префікс.

Загальна оцінка: ~9 розділів + ~30 підрозділів + ~140 класів = ~180 нових records.
Існуючі ~9144 leaf-records отримують parent_id (включно з дублікатами кодів).
"""

import json
import logging

_logger = logging.getLogger(__name__)


def _digit_prefix(code):
    """Return the digit prefix of a KP code (strip ".N", "-N" suffixes)."""
    if not code:
        return ''
    return code.split('.')[0].split('-')[0]


def migrate(cr, version):
    # 1) Get all distinct codes
    cr.execute("SELECT DISTINCT code FROM hr_kp2010 WHERE code IS NOT NULL")
    distinct_codes = [row[0] for row in cr.fetchall()]
    digit_prefixes = {_digit_prefix(c) for c in distinct_codes if _digit_prefix(c)}

    # 2) Determine which intermediate codes to create (prefixes that don't exist)
    needed = set()
    for prefix in digit_prefixes:
        for length in (1, 2, 3):
            if length < len(prefix):
                needed.add(prefix[:length])

    to_create = sorted(needed - set(distinct_codes), key=lambda x: (len(x), x))
    _logger.info('Creating %d intermediate KP2010 levels', len(to_create))

    # 3) Create intermediate records (translatable JSONB name)
    LEVEL_NAMES = {1: 'Розділ', 2: 'Підрозділ', 3: 'Клас'}
    for prefix in to_create:
        name_uk = f'{LEVEL_NAMES[len(prefix)]} {prefix}'
        name_json = json.dumps({'en_US': name_uk, 'uk_UA': name_uk})
        cr.execute("""
            INSERT INTO hr_kp2010 (code, name, group_code, active, create_date, write_date)
            VALUES (%s, %s::jsonb, %s, true, now(), now())
        """, (prefix, name_json, prefix[0]))

    # 4) Build code → MIN(id) map for parent lookup (one canonical parent per code)
    cr.execute("SELECT code, MIN(id) FROM hr_kp2010 WHERE code IS NOT NULL GROUP BY code")
    code_min_id = dict(cr.fetchall())

    # 5) For each child code (including duplicates), find longest existing parent prefix
    # and update ALL records with that code at once via UPDATE WHERE code=...
    updated = 0
    for child_code in distinct_codes + to_create:
        digits = _digit_prefix(child_code)
        if len(digits) <= 1:
            continue
        # Try parent prefixes from longest to shortest
        parent_id = None
        for parent_len in range(len(digits) - 1, 0, -1):
            parent_code = digits[:parent_len]
            if parent_code in code_min_id and code_min_id[parent_code] != code_min_id.get(child_code):
                parent_id = code_min_id[parent_code]
                break
        if parent_id is not None:
            # Update ALL records matching this code
            cr.execute(
                "UPDATE hr_kp2010 SET parent_id = %s WHERE code = %s AND parent_id IS NULL",
                (parent_id, child_code),
            )
            updated += cr.rowcount

    _logger.info('Updated parent_id for %d records', updated)

    # 6) Re-compute `level` for all records (SQL INSERTs bypass ORM compute).
    # level: 1/2/3 for digit prefixes, 4 for >= 4 digits (or with dots).
    cr.execute("""
        UPDATE hr_kp2010
           SET level = CASE
               WHEN length(split_part(split_part(code, '.', 1), '-', 1)) <= 1 THEN '1'
               WHEN length(split_part(split_part(code, '.', 1), '-', 1)) = 2 THEN '2'
               WHEN length(split_part(split_part(code, '.', 1), '-', 1)) = 3 THEN '3'
               ELSE '4'
           END
         WHERE code IS NOT NULL
    """)
    _logger.info('Re-computed level for all KP2010 records')
