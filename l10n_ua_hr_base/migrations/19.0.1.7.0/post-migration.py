"""Restate staffing salaries in the money of the company that keeps them.

`hr.staffing.table.currency_id` defaulted to the currency of the company in
the switcher rather than of the company on the line, and the field is on the
form for nobody outside multi-currency. A line written for company A while the
officer was looking at company B therefore carries B's currency over A's
number.

What that number means now depends on the rate table, and so does what may be
done about it here:

* no rate for the currency anywhere — nothing has ever converted this figure
  and nothing could: `_salary_in_company_currency` refuses, and every payslip
  that reached the position stopped. The number was entered, read and printed
  as the company's own money. The currency is corrected to say so.
* a rate on file — the salary has been going into payslips multiplied by it,
  and from here there is no telling whether that was the intent (a position
  genuinely priced in another currency is legitimate, and the helper exists
  for it) or the default nobody could see. Rewriting it would move somebody's
  salary by a factor of forty on a guess. Those lines are left alone and
  reported instead: in the log, and in the chatter of each line, where the
  officer who has to decide will come looking.
"""

import logging
from collections import defaultdict

from odoo import SUPERUSER_ID, api

from odoo.addons.l10n_ua_hr_base.models.hr_version import _l10n_ua_has_rate

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    # The notes below are read by the HR officer, not by the superuser who
    # happens to run the upgrade: without this a Ukrainian installation gets
    # them in English purely because nobody ever set a language on that user.
    installed = env['res.lang'].get_installed()
    env = api.Environment(cr, SUPERUSER_ID, {
        'lang': env.user.lang or (installed[0][0] if installed else 'en_US'),
    })
    Staffing = env['hr.staffing.table']
    lines = Staffing.search([])
    mismatched = lines.filtered(
        lambda line: line.company_id.currency_id
        and line.currency_id != line.company_id.currency_id)
    if not mismatched:
        return

    healed = Staffing.browse()
    flagged = Staffing.browse()
    for line in mismatched:
        if line.currency_id and _l10n_ua_has_rate(
                env, line.currency_id, line.company_id):
            flagged |= line
        else:
            healed |= line

    if healed:
        # Read before the write: the note names the currency the line used to
        # carry, and after the write every one of them says the company's own.
        previous = {line.id: line.currency_id.name for line in healed}

        # One write per target currency, and tracking off: the chatter note
        # below says what happened and why, which a bare "Currency: USD -> UAH"
        # would not.
        by_currency = defaultdict(list)
        for line in healed:
            by_currency[line.company_id.currency_id.id].append(line.id)
        for currency_id, ids in by_currency.items():
            Staffing.browse(ids).with_context(
                tracking_disable=True).write({'currency_id': currency_id})

        healed._message_log_batch({
            line.id: env._(
                'The salary on this line was stated in %(old)s, the currency '
                'of whichever company was selected when it was created, while '
                'the line belongs to %(company)s and its salary was entered, '
                'read and printed as %(new)s. No rate for %(old)s was ever on '
                'file, so nothing could convert the figure and every payslip '
                'that reached this position stopped. The currency now says '
                'what the number always meant.',
                old=previous[line.id],
                new=line.company_id.currency_id.name,
                company=line.company_id.display_name)
            if previous[line.id] else env._(
                'The salary on this line named no currency at all, so '
                'everything that read it — payroll, the printed staffing '
                'table — took the figure for %(new)s, the currency of '
                '%(company)s. The currency now says what the number always '
                'meant.',
                new=line.company_id.currency_id.name,
                company=line.company_id.display_name)
            for line in healed
        })
        _logger.info(
            'l10n_ua_hr_base 19.0.1.7.0: %s staffing line(s) restated in the '
            'currency of their own company; no rate existed for the currency '
            'they carried, where they carried one at all, so the figures were '
            'hryvnia in all but name: %s',
            len(healed), healed.ids)

    if flagged:
        flagged._message_log_batch({
            line.id: env._(
                'The salary on this line is stated in %(currency)s, not in '
                '%(company_currency)s, the currency of %(company)s. Until now '
                'the currency was filled in from the company selected at the '
                'time of writing, not from the line, so this may never have '
                'been intended — and payroll converts the figure at the rate '
                'of the period it calculates, which is not what an officer '
                'entering a hryvnia salary expects. A rate is on file, so the '
                'number has been reaching payslips multiplied by it. Check it: '
                'if the position is not priced in %(currency)s, correct the '
                'currency here.',
                currency=line.currency_id.name,
                company_currency=line.company_id.currency_id.name,
                company=line.company_id.display_name)
            for line in flagged
        })
        _logger.warning(
            'l10n_ua_hr_base 19.0.1.7.0: %s staffing line(s) state their '
            'salary in a currency other than their own company\'s, and a rate '
            'for it exists, so payroll has been converting them. Whether that '
            'was intended cannot be decided here and the lines are left as '
            'they are — each carries a note in its chatter: %s',
            len(flagged), flagged.ids)
