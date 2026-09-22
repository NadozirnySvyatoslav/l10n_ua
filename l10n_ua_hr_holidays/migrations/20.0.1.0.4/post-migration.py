from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Finish the switch to period-based vacation accounting.

    Runs AFTER the ORM has loaded the new schema (vacation_balance_id on
    hr_leave exists, period_type is stored on the balance):

    1. Realigns work-year balances: pre-migration backfilled everything
       as calendar years; rows whose leave type accrues per work year get
       their bounds re-anchored to the employee's hire anniversary.
       The mapping keeps the row's original year as the anniversary year,
       so `year` (= period_start.year) and year-based reports stay stable.
       Done through the ORM (_reanchor_period) so the hire_date →
       contract_date_start fallback applies — plain SQL cannot reach the
       employee's current version.
    2. Links legacy leaves to their balance row — first by an explicitly
       set vacation_year, then by date containment.
    3. Recomputes the stored rollups and labels through the ORM so the
       values reflect the corrected periods.
    """
    # 0. UA-categorized leave types must not demand core allocations —
    #    entitlement is tracked via hr.vacation.balance. The data file is
    #    noupdate=1 and the ORM forbids flipping requires_allocation once
    #    leaves of the type exist, so plain SQL is the only clean path.
    cr.execute("""
        UPDATE hr_leave_type
           SET requires_allocation = false
         WHERE ua_leave_category IS NOT NULL
           AND requires_allocation = true
    """)

    # 1. Work-year balances: re-anchor bounds to the hire anniversary
    env = api.Environment(cr, SUPERUSER_ID, {})
    work_balances = env['hr.vacation.balance'].search(
        [('period_type', '=', 'work')])
    for balance in work_balances:
        balance._reanchor_period()

    # 2a. Link leaves with an explicit vacation_year to that year's balance.
    #     The date-containment guard is required: for work-year balances the
    #     bounds were re-anchored to the hire anniversary in step 1, so a
    #     leave's vacation_year (a plain calendar year) may match vb.year while
    #     its start date falls into a *different* work-year window. Without the
    #     guard such a leave would be mis-linked to a period it is not inside,
    #     and _check_vacation_balance_period would later reject any edit.
    cr.execute("""
        UPDATE hr_leave l
           SET vacation_balance_id = vb.id
          FROM hr_vacation_balance vb
         WHERE vb.employee_id = l.employee_id
           AND vb.leave_type_id = l.holiday_status_id
           AND l.vacation_balance_id IS NULL
           AND l.vacation_year IS NOT NULL
           AND l.vacation_year != 0
           AND l.vacation_year = vb.year
           AND l.request_date_from IS NOT NULL
           AND l.request_date_from BETWEEN vb.period_start AND vb.period_end
    """)

    # 2b. Link remaining leaves by date containment
    cr.execute("""
        UPDATE hr_leave l
           SET vacation_balance_id = vb.id
          FROM hr_vacation_balance vb
         WHERE vb.employee_id = l.employee_id
           AND vb.leave_type_id = l.holiday_status_id
           AND l.vacation_balance_id IS NULL
           AND l.request_date_from IS NOT NULL
           AND l.request_date_from BETWEEN vb.period_start AND vb.period_end
    """)

    # 3. Refresh stored computes affected by the SQL updates above
    #    (display_name is Odoo's on-the-fly compute from _rec_name, nothing
    #    to recompute here).
    balances = env['hr.vacation.balance'].search([])
    if balances:
        balances.invalidate_recordset()
        balances._compute_year()
        balances._compute_period_label()
        balances._compute_used_days()
        balances._compute_totals()

