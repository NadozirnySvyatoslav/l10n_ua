# Commissioning entries (Дт 10х / Кт 152, #628) are new. Assets that were
# commissioned before the upgrade already have their initial cost on the
# books (opening balance, vendor bill, manual entry), so they must never get
# such an entry, not even after being reset to draft and commissioned again.
#
# The document date of MNMA / MSHP (#626) got the upgrade day as default on
# existing rows; empty means "today" at the moment of the operation, which is
# what an untouched default should mean.


def migrate(cr, version):
    cr.execute("""
        UPDATE l10n_ua_asset
           SET no_commission_move = TRUE
         WHERE state != 'draft'
    """)
    cr.execute("UPDATE l10n_ua_mnma SET document_date = NULL")
    cr.execute("UPDATE l10n_ua_mshp SET document_date = NULL")
