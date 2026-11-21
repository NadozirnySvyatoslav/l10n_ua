# The document date of MNMA / MSHP (#626) got the upgrade day as default on
# existing rows; empty means "today" at the moment of the operation, which is
# what an untouched default should mean.


def migrate(cr, version):
    cr.execute("UPDATE l10n_ua_mnma SET document_date = NULL")
    cr.execute("UPDATE l10n_ua_mshp SET document_date = NULL")
