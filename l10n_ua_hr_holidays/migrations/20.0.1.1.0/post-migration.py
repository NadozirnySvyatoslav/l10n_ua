import logging

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Drop the vacation periods backfilled from the hire date (#629).

    Until now the chain of hr.vacation.balance was generated from the hire
    date, so an employee hired in 2017 without any vacation recorded in Odoo
    got a period for every work year since, each carrying 24 "unused" days
    into the next. The chain now starts at the recorded history (see
    hr.vacation.balance._chain_start), and the leading periods generated
    without it are removed here:

    * only from a chain whose first period has no Carried Over of its own —
      a non-zero one there was typed in by hand as an opening balance;
    * only leading periods that ended before today, have no leave charged
      or planned on them, are not referenced by a vacation schedule and keep
      the default entitlement — anything else is data somebody entered.

    The first remaining period of a trimmed chain starts with no Carried
    Over, and the chain is recomputed.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Balance = env['hr.vacation.balance'].with_context(active_test=False)
    Leave = env['hr.leave'].with_context(active_test=False)
    Schedule = env['hr.vacation.schedule.line'] \
        if 'hr.vacation.schedule.line' in env else None
    today = fields.Date.today()

    cr.execute("""
        SELECT DISTINCT employee_id, leave_type_id FROM hr_vacation_balance
    """)
    removed = 0
    trimmed = Balance.browse()
    for employee_id, leave_type_id in cr.fetchall():
        chain = Balance.search([
            ('employee_id', '=', employee_id),
            ('leave_type_id', '=', leave_type_id),
        ], order='period_start')
        if not chain or chain[0].carried_over:
            continue
        drop = Balance.browse()
        for bal in chain:
            if bal.period_end >= today:
                break
            if Leave.search_count([
                    ('employee_id', '=', employee_id),
                    ('work_entry_type_id', '=', leave_type_id),
                    '|', ('vacation_balance_id', '=', bal.id),
                         '&', ('request_date_from', '>=', bal.period_start),
                              ('request_date_from', '<=', bal.period_end)]):
                break
            if Schedule is not None and 'vacation_balance_id' in Schedule._fields \
                    and Schedule.search_count([('vacation_balance_id', '=', bal.id)]):
                break
            annual = bal.leave_type_id.annual_days or 0
            span = (bal.period_end - bal.period_start).days + 1
            default = annual if span >= 365 else round(annual * span / 365.0, 2)
            if bal.entitled_days != default:
                break
            drop |= bal
        if not drop:
            continue
        rest = chain - drop
        removed += len(drop)
        drop.unlink()
        if rest:
            rest[0].carried_over = 0
            trimmed |= rest[0]
    if trimmed:
        trimmed._recompute_carryover_chain()
    _logger.info(
        'l10n_ua_hr_holidays: removed %d vacation periods backfilled from the '
        'hire date without history; %d chains recomputed.',
        removed, len(trimmed))
