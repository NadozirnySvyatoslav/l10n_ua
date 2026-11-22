# The document sequences were created for the installing company only (the
# data had no company_id), so every other company got "New" as a number.
# The data file is noupdate: share the existing records here.


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_sequence s SET company_id = NULL
          FROM ir_model_data d
         WHERE d.model = 'ir.sequence' AND d.res_id = s.id
           AND d.module = 'l10n_ua_accounting' AND d.name = 'seq_currency_exchange'
    """)
