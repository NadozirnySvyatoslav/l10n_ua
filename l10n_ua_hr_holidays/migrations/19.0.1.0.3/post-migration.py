def migrate(cr, version):
    """Set period_type='work' for annual vacation types.

    Data file hr_leave_type_data.xml is loaded with noupdate="1" — existing
    records on upgraded installations would not pick up the new period_type
    XML field from the data file. This SQL update aligns them with the law:
    annual (basic + additional) and additional-for-working-conditions types
    accrue per work year (ZU "Про відпустки" art. 6, 7, 8, 10).
    """
    cr.execute("""
        UPDATE hr_leave_type
           SET period_type = 'work'
         WHERE ua_leave_category IN (
                   'annual_basic', 'annual_additional',
                   'annual_hazardous', 'annual_special', 'annual_irregular')
           AND (period_type IS NULL OR period_type = 'calendar')
    """)
