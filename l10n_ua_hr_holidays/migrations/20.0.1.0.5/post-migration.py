def migrate(cr, version):
    """Enable "Auto-calculate Balance" for the annual basic leave type across
    every company.

    ua_auto_calc_balance defaults to False, but the annual basic vacation is
    the one whose balance should be recalculated out of the box, so switch it
    on for all annual_basic leave types (one per company). Plain SQL is used
    because the leave-type data file is noupdate=1 and existing per-company
    rows are created by an action rather than XML.
    """
    cr.execute("""
        UPDATE hr_leave_type
           SET ua_auto_calc_balance = true
         WHERE ua_leave_category = 'annual_basic'
    """)

