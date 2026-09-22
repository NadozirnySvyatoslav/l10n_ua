"""Migration #88 + #90 — military_fitness ('limited' → 'temp_unfit')
                        + military_register_category seeding from legacy military_status.

#88 — Закон № 3621-IX від 04.05.2024 скасував категорію «обмежено придатний».
      Legacy 'limited' values migrate to 'temp_unfit' as a conservative default.
      HR officers can re-evaluate to 'fit_support' case-by-case.

#90 — ПКМУ № 1487 від 30.12.2022 визначає три категорії військового обліку:
      conscript (призовник), liable (військовозобов'язаний), reservist (резервіст).
      Legacy military_status ('liable'/'reserved'/'exempt'/'not_applicable')
      is partially compatible: existing 'liable' → 'liable', 'reserved'/'exempt' →
      'liable' (Reserved/Exempt не є категоріями обліку; це окремий стан).
      Old field is preserved (legacy) to keep historical reports working.
"""


def migrate(cr, version):
    # #88 — military_fitness migration
    cr.execute("""
        UPDATE hr_employee
           SET military_fitness = 'temp_unfit'
         WHERE military_fitness = 'limited'
    """)

    # #90 — Seed military_register_category from legacy military_status
    # Default: not_applicable. Migrate 'liable' as-is; reserved/exempt fold to 'liable'
    # (because they imply liability — just specific operational state).
    cr.execute("""
        UPDATE hr_employee
           SET military_register_category = CASE
               WHEN military_status = 'liable'   THEN 'liable'
               WHEN military_status = 'reserved' THEN 'liable'
               WHEN military_status = 'exempt'   THEN 'liable'
               ELSE 'not_applicable'
           END
         WHERE military_register_category IS NULL
            OR military_register_category = 'not_applicable'
    """)
