def migrate(cr, version):
    """Prepare hr_vacation_balance for period-based accounting.

    Runs BEFORE the ORM loads the new model definition:
    1. Adds the period columns so the NOT NULL constraints of the new
       required fields can be satisfied for existing rows.
    2. Backfills them from the legacy integer `year` (calendar-year
       semantics — the only semantics that existed so far). Work-year
       rows are corrected in post-migration once period_type is known.
    3. Drops the old unique constraint so the ORM can create the new
       (employee_id, leave_type_id, period_start) one without conflict.
    """
    cr.execute("""
        ALTER TABLE hr_vacation_balance
            ADD COLUMN IF NOT EXISTS period_start date,
            ADD COLUMN IF NOT EXISTS period_end date,
            ADD COLUMN IF NOT EXISTS period_index integer
    """)
    cr.execute("""
        UPDATE hr_vacation_balance
           SET period_start = make_date(year, 1, 1),
               period_end = make_date(year, 12, 31),
               period_index = year
         WHERE period_start IS NULL
           AND year IS NOT NULL
    """)
    cr.execute("""
        ALTER TABLE hr_vacation_balance
            DROP CONSTRAINT IF EXISTS
                hr_vacation_balance_unique_employee_id_leave_type_id_year
    """)

