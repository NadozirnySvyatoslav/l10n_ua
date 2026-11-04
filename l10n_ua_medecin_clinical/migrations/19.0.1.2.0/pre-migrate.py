"""Типізовані діагнози (#225).

До 19.0.1.2.0 діагноз мав лише ознаку `is_primary`. Тепер джерело істини —
`diagnosis_type`, а `is_primary` обчислюється з нього (== 'final'). Створюємо
колонки заздалегідь, щоб Odoo не заповнив усі рядки значенням за
замовчуванням і не розсинхронізував їх з `is_primary`:

* is_primary = True  → diagnosis_type = 'final' (заключний/основний)
* is_primary = False → diagnosis_type = 'clinical' (нейтральний тип)
* date_established   ← календарна дата прийому (Europe/Kyiv)
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns "
               "WHERE table_name = 'l10n_ua_medecin_diagnosis' "
               "AND column_name = 'diagnosis_type'")
    if cr.fetchone():
        return
    cr.execute("""
        ALTER TABLE l10n_ua_medecin_diagnosis
            ADD COLUMN diagnosis_type varchar,
            ADD COLUMN date_established date
    """)
    cr.execute("""
        UPDATE l10n_ua_medecin_diagnosis
           SET diagnosis_type = CASE WHEN is_primary THEN 'final' ELSE 'clinical' END,
               date_established = (date_start AT TIME ZONE 'UTC'
                                   AT TIME ZONE 'Europe/Kyiv')::date
    """)
