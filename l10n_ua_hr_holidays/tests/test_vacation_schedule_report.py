from datetime import date
from odoo.tests.common import TransactionCase


class TestVacationScheduleReport(TransactionCase):
    """PR 3: vacation schedule and summary report work with both accounting
    period types (calendar year and work year)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Schedule Test Employee',
            'hire_date': date(2024, 7, 15),
        })
        # annual_basic and annual_additional accrue on a WORK year;
        # social_children on a CALENDAR year.
        cls.annual_type = cls.env.ref(
            'l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.additional_type = cls.env.ref(
            'l10n_ua_hr_holidays.leave_type_annual_additional')
        cls.social_type = cls.env.ref(
            'l10n_ua_hr_holidays.leave_type_social_children')

    def _create_leave(self, leave_type, date_from, date_to, **extra):
        vals = {
            'name': 'Test leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': leave_type.id,
            'request_date_from': date_from,
            'request_date_to': date_to,
        }
        vals.update(extra)
        leave = self.env['hr.leave'].create(vals)
        # Odoo 20 auto-approves a leave created by a Time Off Officer
        # (hr_holidays._process_auto_approve_activities), and the tests run
        # as admin. Put it back to "To Approve" so the fixture describes a
        # freshly requested leave, the way it did on 19.
        if leave.state == 'validate':
            leave.sudo().state = 'confirm'
        return leave

    def _new_schedule(self, year, company=None):
        """Create a vacation schedule for (year, company), first removing any
        existing one for that pair. unique(year, company_id) is a global DB
        constraint, so a row left over from another test or a previous run on a
        persistent DB would otherwise make the create clash."""
        company = company or self.employee.company_id
        self.env['hr.vacation.schedule'].search([
            ('year', '=', year),
            ('company_id', '=', company.id),
        ]).unlink()
        return self.env['hr.vacation.schedule'].create({
            'year': year,
            'company_id': company.id,
        })

    def _work_period(self, leave_type, start, end, index, employee=None,
                     **extra):
        """Create a work-year accounting period for the given employee/type."""
        vals = {
            'employee_id': (employee or self.employee).id,
            'leave_type_id': leave_type.id,
            'period_start': start,
            'period_end': end,
            'period_index': index,
            'entitled_days': 24,
        }
        vals.update(extra)
        return self.env['hr.vacation.balance'].create(vals)

    # ------------------------------------------------------------------
    # Schedule: planned days pulled from the right period
    # ------------------------------------------------------------------

    def test_schedule_leaf_shows_its_charged_period(self):
        """A leave is picked by its START DATE (in the schedule year) and its
        row shows the accounting period it is charged to, even when the leave
        dates fall outside that period — e.g. a March 2026 leave taken against
        the 2024/25 period appears in the 2026 schedule with that period."""
        past_period = self._work_period(
            self.annual_type, date(2024, 7, 15), date(2025, 7, 14), 1)
        # Leave dated March 2026, charged to the past period (dates outside it).
        leave = self._create_leave(
            self.annual_type, date(2026, 3, 2), date(2026, 3, 6),
            vacation_balance_id=past_period.id)

        schedule = self._new_schedule(2026, self.employee.company_id)
        schedule.action_generate_lines()

        line = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee and l.leave_id == leave)
        self.assertEqual(len(line), 1)
        # The row shows the charged period...
        self.assertEqual(line.vacation_balance_id, past_period)
        # ...and its "Month / vacation period" cell is never empty.
        self.assertTrue(line.vacation_period_display)

    def test_schedule_leaf_outside_year_not_shown(self):
        """A leave whose start date is NOT in the schedule year is not listed,
        even if its charged period would otherwise match."""
        period = self._work_period(
            self.annual_type, date(2024, 7, 15), date(2025, 7, 14), 1)
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 1), date(2025, 9, 5),
            vacation_balance_id=period.id)

        schedule = self._new_schedule(2026, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        self.assertFalse(lines.filtered(lambda l: l.leave_id == leave))

    # ------------------------------------------------------------------
    # Schedule: one row per leave, actual days per leave
    # ------------------------------------------------------------------

    def test_schedule_one_row_per_leave(self):
        """An employee with several planned leaves gets one row per leave, each
        carrying its own type, period, calendar days and dates."""
        basic = self._create_leave(
            self.annual_type, date(2025, 2, 10), date(2025, 2, 14))
        additional = self._create_leave(
            self.additional_type, date(2025, 8, 1), date(2025, 8, 3))

        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        # Exactly one row per planned leave (past-period rows, if any, are
        # counted separately and are not leave-linked).
        leaf_lines = lines.filtered(lambda l: l.leave_id)
        self.assertEqual(len(leaf_lines), 2)

        basic_line = lines.filtered(lambda l: l.leave_id == basic)
        add_line = lines.filtered(lambda l: l.leave_id == additional)
        self.assertTrue(basic_line and add_line)

        # Each row mirrors its own leave: type, balance, days and dates.
        self.assertEqual(basic_line.leave_type_id, self.annual_type)
        self.assertEqual(basic_line.vacation_balance_id,
                         basic.vacation_balance_id)
        self.assertEqual(basic_line.planned_days, basic.calendar_days)
        self.assertEqual(basic_line.vacation_period_display,
                         '10.02.2025 - 14.02.2025')
        self.assertEqual(add_line.leave_type_id, self.additional_type)
        self.assertEqual(add_line.vacation_period_display,
                         '01.08.2025 - 03.08.2025')
        # Job position is mirrored from the employee.
        self.assertEqual(basic_line.job_id, self.employee.job_id)

    def test_schedule_actual_days_per_leave(self):
        """actual_days on a row equals the linked leave's calendar days once it
        is approved, and 0 while it is still only planned."""
        basic = self._create_leave(
            self.annual_type, date(2025, 2, 10), date(2025, 2, 14))
        basic.action_approve()
        additional = self._create_leave(
            self.additional_type, date(2025, 8, 1), date(2025, 8, 3))
        # additional stays in a planning state (not approved)

        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        basic_line = lines.filtered(lambda l: l.leave_id == basic)
        add_line = lines.filtered(lambda l: l.leave_id == additional)
        self.assertEqual(basic_line.actual_days, basic.calendar_days)
        self.assertEqual(add_line.actual_days, 0)

    def test_schedule_empty_period_not_shown(self):
        """A period with NO leave charged to it is NOT listed, even when it has
        full entitlement available — only periods with linked leaves appear."""
        bal = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
            'carried_over': 6,
        })
        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        self.assertFalse(
            lines.filtered(lambda l: l.vacation_balance_id == bal))

    def test_schedule_hides_untouched_past_period(self):
        """A past period with NO leaves taken (used = 0) is not listed, even
        though its whole entitlement is technically unused - only partially
        used past periods are shown."""
        untouched = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        self.assertEqual(untouched.used_days, 0)

        schedule = self._new_schedule(2027, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        self.assertFalse(
            lines.filtered(lambda l: l.vacation_balance_id == untouched))

    def test_schedule_no_rows_when_no_leaves(self):
        """An employee with no leave starting in the schedule year gets NO rows
        at all — there is no placeholder, so the report never has empty date
        cells. (A balance with unused days but no leave does not add a row.)"""
        emp = self.env['hr.employee'].create({
            'name': 'No Leaves',
            'hire_date': date(2024, 6, 1),
        })
        self.env['hr.vacation.balance'].create({
            'employee_id': emp.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 6, 1),
            'period_end': date(2026, 5, 31),
            'period_index': 2,
            'entitled_days': 24,
        })

        schedule = self._new_schedule(2026, emp.company_id)
        schedule.action_generate_lines()

        self.assertFalse(
            schedule.line_ids.filtered(lambda l: l.employee_id == emp))

    def test_schedule_includes_non_annual_balance_types(self):
        """A leave of any tracked type (e.g. Chornobyl additional leave, which
        is neither annual_basic nor annual_additional) appears in the schedule,
        matching what is shown in Vacation Balances."""
        chornobyl = self.env.ref('l10n_ua_hr_holidays.leave_type_chornobyl')
        leave = self.env['hr.leave'].create({
            'name': 'Chornobyl leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': chornobyl.id,
            'request_date_from': date(2025, 4, 1),
            'request_date_to': date(2025, 4, 4),
        })
        leave.action_approve()

        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(
            lambda l: l.employee_id == self.employee)
        chorn_line = lines.filtered(lambda l: l.leave_id == leave)
        self.assertEqual(len(chorn_line), 1)
        self.assertEqual(chorn_line.leave_type_id, chornobyl)

    def test_schedule_period_without_leave_hidden_other_type_shown(self):
        """A period with NO leave charged to it is not listed, but a leave of
        another type still shows: the empty annual basic period is hidden while
        the Chornobyl leave appears."""
        chornobyl = self.env.ref('l10n_ua_hr_holidays.leave_type_chornobyl')
        # Hired Jan 1 -> the annual basic work year is the calendar year 2026.
        emp = self.env['hr.employee'].create({
            'name': 'January Hire',
            'hire_date': date(2026, 1, 1),
        })
        basic_bal = self.env['hr.vacation.balance'].create({
            'employee_id': emp.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2026, 1, 1),
            'period_end': date(2026, 12, 31),
            'period_index': 1,
            'entitled_days': 24,
        })
        # A leave of a DIFFERENT type (Chornobyl) in 2026 — the annual basic
        # period stays leaveless.
        self.env['hr.leave'].create({
            'name': 'Chornobyl 2026',
            'employee_id': emp.id,
            'work_entry_type_id': chornobyl.id,
            'request_date_from': date(2026, 4, 1),
            'request_date_to': date(2026, 4, 4),
        }).action_approve()

        schedule = self._new_schedule(2026, emp.company_id)
        schedule.action_generate_lines()

        lines = schedule.line_ids.filtered(lambda l: l.employee_id == emp)
        # The Chornobyl leave shows...
        self.assertTrue(lines.filtered(lambda l: l.leave_type_id == chornobyl))
        # ...but the annual basic period (no leave charged) is NOT listed.
        self.assertFalse(
            lines.filtered(lambda l: l.vacation_balance_id == basic_bal))

    def test_report_lines_grouped_by_employee(self):
        """The PDF report helper groups an employee's leave rows so the name/No/
        job cells rowspan across all of them, and leaves of different types are
        separate type-groups (separate "Leave Type" cells)."""
        # Link each leave to the schedule year's own work period so the
        # schedule lists exactly one row per leave (no extra current-period row
        # for a period the leaf leaves uncovered).
        annual_bal = self._work_period(
            self.annual_type, date(2024, 7, 15), date(2025, 7, 14), 1)
        add_bal = self._work_period(
            self.additional_type, date(2024, 7, 15), date(2025, 7, 14), 1)
        self._create_leave(
            self.annual_type, date(2025, 2, 10), date(2025, 2, 14),
            vacation_balance_id=annual_bal.id)
        self._create_leave(
            self.additional_type, date(2025, 8, 1), date(2025, 8, 3),
            vacation_balance_id=add_bal.id)

        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        groups = schedule._report_lines_grouped()
        emp_group = [g for g in groups if g['employee'] == self.employee]
        self.assertEqual(len(emp_group), 1)
        grp = emp_group[0]
        self.assertEqual(grp['total'], 2)
        # Two different types -> two type-groups, one line each.
        self.assertEqual(len(grp['type_groups']), 2)
        self.assertEqual(len(grp['type_groups'][0]['lines']), 1)

    def test_report_merges_same_leave_type(self):
        """Two leaves of the SAME type merge into one type-group, so the
        "Leave Type" cell rowspans both rows."""
        # Both leaves charged to the same schedule-year work period, so the
        # schedule lists exactly the two leaf rows (no extra current-period
        # row).
        annual_bal = self._work_period(
            self.annual_type, date(2024, 7, 15), date(2025, 7, 14), 1)
        self._create_leave(
            self.annual_type, date(2025, 2, 10), date(2025, 2, 14),
            vacation_balance_id=annual_bal.id)
        self._create_leave(
            self.annual_type, date(2025, 6, 2), date(2025, 6, 6),
            vacation_balance_id=annual_bal.id)

        schedule = self._new_schedule(2025, self.employee.company_id)
        schedule.action_generate_lines()

        grp = [g for g in schedule._report_lines_grouped()
               if g['employee'] == self.employee][0]
        self.assertEqual(grp['total'], 2)
        # Same type -> a single type-group covering both rows.
        self.assertEqual(len(grp['type_groups']), 1)
        self.assertEqual(grp['type_groups'][0]['leave_type'], self.annual_type)
        self.assertEqual(len(grp['type_groups'][0]['lines']), 2)

    # ------------------------------------------------------------------
    # Summary report: both period types for the selected year
    # ------------------------------------------------------------------

    def test_summary_report_mixed_periods(self):
        """The summary report gathers, per employee/leave type, the period the
        selected date falls into (31.12.2025 here) — the same selection as the
        "Vacation Balances" report — covering both calendar-year and work-year
        period types."""
        # A calendar-year balance for the report year.
        cal_bal = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.social_type.id,
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'period_index': 2025,
            'entitled_days': 10,
        })

        report = self.env['hr.employee.vacation.summary.report'].create({
            'report_date': date(2025, 12, 31),
            'company_id': self.employee.company_id.id,
        })
        # generate_balances backfills the annual_basic (work-year) balances up
        # to the selected date; the work year and the calendar balance above
        # both contain 2025-12-31, so both are picked up.
        report.action_generate()

        period_types = set(report.balance_ids.mapped('period_type'))
        self.assertIn('calendar', period_types)
        self.assertIn('work', period_types)
        self.assertIn(cal_bal.id, report.balance_ids.ids)

        work = report.balance_ids.filtered(
            lambda b: b.period_type == 'work'
            and b.employee_id == self.employee)
        self.assertTrue(work)
