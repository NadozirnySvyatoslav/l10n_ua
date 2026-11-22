# The report sequence was created for the installing company only (the data
# had no company_id), so every other company got "/" as a report number.
# The data file is noupdate: share the existing record here.


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_sequence s SET company_id = NULL
          FROM ir_model_data d
         WHERE d.model = 'ir.sequence' AND d.res_id = s.id
           AND d.module = 'l10n_ua_hr_business_trip'
    """)
