"""Ф3: row codes of sections II and III follow Додаток 1 до НП(С)БО 1 (#78).

Reports saved before kept the codes of an earlier draft of the form
(3220 for the interest received, 3250/3255 for the purchases, 3350–3360 for
the financing payments), which are other rows of the official form and of the
XML J0900904. The rows are renamed by their key, so a confirmed report keeps
its amounts under the right code.
"""

RENAMES = {
    'inv_in_interest': '3215',
    'inv_out_financial': '3255',
    'inv_out_noncurrent': '3260',
    'fin_out_buyback': '3345',
    'fin_out_loans': '3350',
    'fin_out_dividends': '3355',
}


def migrate(cr, version):
    if not version:
        return
    for key, code in RENAMES.items():
        cr.execute(
            "UPDATE l10n_ua_cashflow_report_line SET code = %s WHERE flow_key = %s",
            (code, key))
