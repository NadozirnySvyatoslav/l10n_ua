from datetime import date, datetime
from psycopg2 import IntegrityError
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


class TestVacationPeriodBalance(TransactionCase):
    """PR 2: period-based hr.vacation.balance + vacation_balance_id on hr.leave."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Тестовий Працівник Періодів',
            'hire_date': date(2024, 7, 15),
        })
        cls.annual_type = cls.env.ref(
            'l10n_ua_hr_holidays.leave_type_annual_basic')
        cls.social_type = cls.env.ref(
            'l10n_ua_hr_holidays.leave_type_social_children')
        # generate_balances filters employees on contract_id.state == 'open'.
        # Odoo 19 keeps the contract period on the employee's version, so open
        # one (start set, no end) — otherwise the employee is skipped and no
        # balances are generated for it.
        version = cls.employee.with_context(active_test=False).version_ids[:1]
        if version:
            version.write({
                'contract_date_start': date(2024, 7, 15),
                'contract_date_end': False,
            })
        # These tests place leaves shortly after hire and do not exercise the
        # 6-month first-annual-leave experience rule (which the open contract
        # above would otherwise activate) — relax it for the annual type used.
        cls.annual_type.requires_experience = False

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

    # ------------------------------------------------------------------
    # Balance period derivation
    # ------------------------------------------------------------------

    def test_period_defaults_to_first_day_and_backfills_chain(self):
        """Saving a leave with no chosen period defaults it to the period the
        leave's FIRST DAY falls into (not today's), and backfills the whole
        period chain from the hire date up to today."""
        leave = self._create_leave(
            self.annual_type, date(2025, 1, 10), date(2025, 1, 20))
        balance = leave.vacation_balance_id
        self.assertTrue(balance)
        # 2025-01-10 falls in work year 1 (2024-07-15 .. 2025-07-14).
        self.assertEqual(balance.period_start, date(2024, 7, 15))
        self.assertEqual(balance.period_end, date(2025, 7, 14))
        self.assertEqual(balance.entitled_days, self.annual_type.annual_days)
        # The backfill still created every work-year period up to today, so the
        # current work year exists too.
        today = date.today()
        self.assertTrue(self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
            ('period_start', '<=', today),
            ('period_end', '>=', today),
        ]))

    def test_period_defaults_to_first_day_calendar_type(self):
        """A calendar leave type (educational) defaults to the Jan 1 – Dec 31
        period the leave's first day falls into."""
        educational = self.env.ref('l10n_ua_hr_holidays.leave_type_educational')
        leave = self._create_leave(
            educational, date(2025, 3, 3), date(2025, 3, 7))
        balance = leave.vacation_balance_id
        self.assertTrue(balance)
        self.assertEqual(balance.period_start, date(2025, 1, 1))
        self.assertEqual(balance.period_end, date(2025, 12, 31))

    def test_period_not_created_when_unresolvable(self):
        """Work-year type without a hire anchor cannot resolve a period, so
                nothing is auto-created and the leave stays unlinked."""
        anchorless = self.env['hr.employee'].create({'name': 'No hire date'})
        leave = self._create_leave(
            self.annual_type, date(2025, 3, 3), date(2025, 3, 7),
            employee_id=anchorless.id)
        self.assertFalse(leave.vacation_balance_id)

    def test_date_change_keeps_chosen_period(self):
        """The accounting period is a manual choice: changing the leave dates
        does NOT re-point the leave at a different period. vacation_year still
        follows the start date and is read-only."""
        # Keep the leave editable regardless of the type's stored validation
        # config: a 'no_validation' type (as a persistent DB may have) would
        # auto-validate on create and then block the date change below.
        self.annual_type.leave_validation_type = 'hr'
        b1 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2025, 1, 10), date(2025, 1, 20),
            vacation_balance_id=b1.id)
        self.assertEqual(leave.vacation_balance_id, b1)
        self.assertEqual(leave.vacation_year, 2025)
        # Moving the dates into the next work year leaves the chosen period
        # untouched, but vacation_year tracks the new start date.
        leave.write({
            'request_date_from': date(2025, 9, 1),
            'request_date_to': date(2025, 9, 10),
            'date_from': datetime(2025, 9, 1, 8, 0, 0),
            'date_to': datetime(2025, 9, 10, 17, 0, 0),
        })
        self.assertEqual(leave.vacation_balance_id, b1)
        self.assertEqual(leave.vacation_year, 2025)

    def test_foreign_period_blocks_save(self):
        """A period belonging to another employee/type is rejected, but a
        period of the right employee+type is accepted even when the leave
        dates fall outside it (the period is a manual choice)."""
        other_emp = self.env['hr.employee'].create({
            'name': 'Інший Працівник',
            'hire_date': date(2024, 7, 15),
        })
        foreign = self.env['hr.vacation.balance'].create({
            'employee_id': other_emp.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2025, 1, 10), date(2025, 1, 20))
        with self.assertRaises(ValidationError):
            leave.vacation_balance_id = foreign
        # A same-employee/type period whose dates don't contain the leave is
        # accepted without complaint. Use a future work year (2027) — the
        # periods up to today were already backfilled when the leave was
        # created, so this one is new and does not collide.
        mine = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2027, 7, 15),
            'period_end': date(2028, 7, 14),
            'period_index': 4,
            'entitled_days': 24,
        })
        leave.vacation_balance_id = mine
        self.assertEqual(leave.vacation_balance_id, mine)

    def test_used_days_counted_by_link_not_dates(self):
        """used_days / planned_days count only the leaves EXPLICITLY linked to
        the period (vacation_balance_id), never leaves whose dates merely fall
        inside the period's span."""
        # Employee hired 2024-07-15:
        #   work year 1: 2024-07-15 .. 2025-07-14  (index 1)
        #   work year 2: 2025-07-15 .. 2026-07-14  (index 2)
        wy1 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        wy2 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        # Leave dates fall inside WY2's span, but HR links it to WY1: it is
        # charged to WY1 by the link, and WY2 stays untouched.
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 3), date(2025, 9, 7),
            vacation_balance_id=wy1.id)
        leave.action_approve()
        self.assertEqual(leave.vacation_balance_id, wy1)
        self.assertEqual(wy1.used_days, leave.calendar_days)
        self.assertEqual(wy2.used_days, 0)
        self.assertEqual(wy2.planned_days, 0)

    def test_unlinked_leave_still_counted_by_its_dates(self):
        """Safety net: a leave left WITHOUT a period (import, a write clearing
        the field) is still charged to the period its start date falls into, so
        used_days never silently understates the days taken."""
        wy2 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 3), date(2025, 9, 7))
        leave.action_approve()
        self.assertEqual(wy2.used_days, leave.calendar_days)

        # Drop the link the way a stray import/write would.
        leave.sudo().write({'vacation_balance_id': False})
        self.assertFalse(leave.vacation_balance_id)

        wy2.invalidate_recordset(
            ['used_days', 'total_available', 'remaining_days'])
        self.assertEqual(wy2.used_days, leave.calendar_days,
                         'Unlinked leave must still count against its period')
        # Compare against the period's own Total Available rather than its
        # entitlement: creating the leave backfills the earlier work year,
        # whose unused days are carried over into this one.
        self.assertEqual(wy2.remaining_days,
                         wy2.total_available - leave.calendar_days)

    def test_validation_links_missing_period(self):
        """Approving a leave that carries no period links it, so the days are
        charged by the explicit link rather than only by the date fallback."""
        self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 3), date(2025, 9, 7))
        leave.sudo().write({'vacation_balance_id': False})
        self.assertFalse(leave.vacation_balance_id)

        leave.action_approve()

        self.assertTrue(leave.vacation_balance_id,
                        'Validation must fill the missing accounting period')
        self.assertEqual(leave.vacation_balance_id.period_start,
                         date(2025, 7, 15))

    def test_period_mismatch_warning_when_dates_outside_period(self):
        """Charging a leave to a period that does not cover its dates stays
        ALLOWED, but raises a non-blocking notice so a wrongly picked period is
        not applied silently."""
        wy1 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        # Dates are in the NEXT work year, charged to WY1 on purpose.
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 3), date(2025, 9, 7),
            vacation_balance_id=wy1.id)

        self.assertTrue(leave.id, 'The leave must still save')
        self.assertEqual(leave.vacation_balance_id, wy1)
        self.assertTrue(leave.period_mismatch_warning)
        self.assertIn('03.09.2025', leave.period_mismatch_warning)

    def test_no_period_mismatch_warning_when_dates_inside(self):
        """No notice when the leave starts inside the period it is charged
        to — the normal case."""
        wy2 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2025, 9, 3), date(2025, 9, 7),
            vacation_balance_id=wy2.id)
        self.assertFalse(leave.period_mismatch_warning)

    def test_overuse_deficit_carries_negative_forward(self):
        """Taking more days than available (e.g. 26 against a 24-day
        entitlement) leaves the period at a negative Remaining, and that
        deficit is carried into the next period: Carried Over and Total
        Available reflect it (24 + (-2) = 22), not a clamped 0 / 24."""
        wy1 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        wy2 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        # A leave longer than the entitlement, charged to WY1 and approved so
        # the days count as used. Dates span all of September -> > 24 days.
        leave = self._create_leave(
            self.annual_type, date(2024, 9, 1), date(2024, 9, 30),
            vacation_balance_id=wy1.id)
        leave.action_approve()
        self.assertGreater(leave.calendar_days, 24)
        self.assertEqual(wy1.used_days, leave.calendar_days)
        # Over-use -> negative remaining on WY1.
        self.assertEqual(wy1.remaining_days, 24 - leave.calendar_days)
        self.assertLess(wy1.remaining_days, 0)
        # The deficit carries forward in full (not clamped to 0).
        self.assertEqual(wy2.carried_over, wy1.remaining_days)
        self.assertEqual(wy2.total_available, 24 + wy1.remaining_days)

    def test_backdated_period_carries_over_to_current(self):
        """Creating a past period (with an unused-days leave) propagates its
        remaining days as Carried Over into the following period."""
        # Current work year (index 2) already exists with no carry-over.
        current = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        self.assertEqual(current.carried_over, 0)

        # Previous work year (index 1) with a leave HR links to it, using 10
        # days. Approve it so the days count as *used* (a draft leave would
        # only count as planned).
        past = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        past_leave = self._create_leave(
            self.annual_type, date(2024, 9, 2), date(2024, 9, 11),
            vacation_balance_id=past.id)
        past_leave.action_approve()
        self.assertEqual(past.used_days, past_leave.calendar_days)

        # The current period now carries the past period's remaining days.
        expected = past.total_available - past.used_days
        self.assertEqual(current.carried_over, expected)
        self.assertEqual(current.total_available, 24 + expected)

    def test_leave_before_hire_is_blocked(self):
        """A leave that starts before the employee's hire date is rejected."""
        with self.assertRaises(ValidationError):
            self._create_leave(
                self.annual_type, date(2023, 5, 1), date(2023, 5, 10))

    def test_calendar_period_before_hire_hidden_and_blocked(self):
        """A calendar-type leave whose whole year precedes the hire date
        offers no Create button, and the balance itself is rejected."""
        social = self.social_type
        # Employee hired 2024-07-15; a 2023 social leave predates hire.
        with self.assertRaises(ValidationError):
            self._create_leave(social, date(2023, 3, 1), date(2023, 3, 5))
        # Direct balance for a fully-pre-hire calendar year is rejected too.
        with self.assertRaises(ValidationError):
            self.env['hr.vacation.balance'].create({
                'employee_id': self.employee.id,
                'leave_type_id': social.id,
                'period_start': date(2023, 1, 1),
                'period_end': date(2023, 12, 31),
                'period_index': 2023,
                'entitled_days': 10,
            })

    def test_default_get_prefills_period_from_leave_context(self):
        """default_get resolves the whole period from the leave form's
        context defaults (employee, type, year)."""
        Balance = self.env['hr.vacation.balance'].with_context(
            default_employee_id=self.employee.id,
            default_leave_type_id=self.annual_type.id,
            default_period_year=2025,
        )
        defaults = Balance.default_get([
            'employee_id', 'leave_type_id', 'company_id',
            'period_start', 'period_end', 'period_index',
        ])
        self.assertEqual(defaults.get('period_start'), date(2025, 7, 15))
        self.assertEqual(defaults.get('period_end'), date(2026, 7, 14))
        self.assertEqual(defaults.get('period_index'), 2)
        self.assertEqual(
            defaults.get('company_id'), self.employee.company_id.id)

    def test_default_get_calendar_type_from_context(self):
        Balance = self.env['hr.vacation.balance'].with_context(
            default_employee_id=self.employee.id,
            default_leave_type_id=self.social_type.id,
            default_period_year=2026,
        )
        defaults = Balance.default_get(
            ['period_start', 'period_end', 'period_index'])
        self.assertEqual(defaults.get('period_start'), date(2026, 1, 1))
        self.assertEqual(defaults.get('period_end'), date(2026, 12, 31))
        self.assertEqual(defaults.get('period_index'), 2026)

    def test_work_period_balance_create(self):
        """Work-year balance derives bounds from hire_date anniversary."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        self.assertEqual(balance.period_type, 'work')
        self.assertEqual(balance.year, 2024)
        self.assertIn('15.07.2024', balance.period_label)
        self.assertIn('14.07.2025', balance.period_label)

    def test_calendar_period_balance_create(self):
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.social_type.id,
            'period_start': date(2025, 1, 1),
            'period_end': date(2025, 12, 31),
            'period_index': 2025,
            'entitled_days': 10,
        })
        self.assertEqual(balance.period_type, 'calendar')
        self.assertEqual(balance.year, 2025)
        self.assertEqual(balance.period_label, '01.01.2025 – 31.12.2025')

    def test_create_with_legacy_year_derives_work_period(self):
        """Legacy create({'year': ...}) still works: the period is derived
        from the leave type's period_type (transfer wizard compatibility)."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'year': 2024,
            'entitled_days': 24,
        })
        self.assertEqual(balance.period_start, date(2024, 7, 15))
        self.assertEqual(balance.period_end, date(2025, 7, 14))
        self.assertEqual(balance.period_index, 1)

    def test_create_with_legacy_year_calendar_type(self):
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.social_type.id,
            'year': 2024,
            'entitled_days': 10,
        })
        self.assertEqual(balance.period_start, date(2024, 1, 1))
        self.assertEqual(balance.period_end, date(2024, 12, 31))

    def test_unique_constraint_on_period_start(self):
        # Deliberately create a duplicate period to prove the unique
        # constraint fires. The IntegrityError is expected and caught here;
        # mute_logger silences the (otherwise alarming) SQL error log line.
        self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
        })
        with self.assertRaises(IntegrityError), \
                mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            self.env['hr.vacation.balance'].create({
                'employee_id': self.employee.id,
                'leave_type_id': self.annual_type.id,
                'period_start': date(2024, 7, 15),
                'period_end': date(2025, 7, 14),
            })
            self.env.flush_all()

    def test_proportional_entitled_days_short_period(self):
        """A shortened period (e.g. termination) prorates entitled days."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            # 8 months out of 12
            'period_end': date(2025, 3, 14),
        })
        # 243 days / 365 * 24 ≈ 15.98
        self.assertAlmostEqual(balance.entitled_days, 24 * 243 / 365.0, places=1)

    # ------------------------------------------------------------------
    # Leave ↔ balance linking
    # ------------------------------------------------------------------

    def test_leave_auto_links_existing_period_of_first_day(self):
        """A new leave links to the EXISTING period that contains its FIRST
        DAY instead of creating a duplicate for it."""
        start_date = date(2025, 1, 10)
        Balance = self.env['hr.vacation.balance']
        start, end, index = Balance._get_period_for(
            self.employee, self.annual_type, start_date)
        balance = Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': start,
            'period_end': end,
            'period_index': index,
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, start_date, date(2025, 1, 20))
        self.assertEqual(leave.vacation_balance_id, balance)

    def test_leave_charges_single_linked_period(self):
        """A leave is charged fully against the single period it is linked to,
        even when its dates span a calendar-year boundary."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'entitled_days': 24,
        })
        leave = self._create_leave(
            self.annual_type, date(2024, 12, 20), date(2025, 1, 5),
            vacation_balance_id=balance.id)
        leave.action_approve()
        self.assertEqual(leave.vacation_balance_id, balance)
        self.assertEqual(balance.used_days, leave.calendar_days)

    def test_leave_auto_creates_and_links_its_balance(self):
        """A leave with no chosen period auto-creates the period its FIRST DAY
        falls into and links to it, so the period shows up in Vacation
        Balances."""
        leave = self._create_leave(
            self.annual_type, date(2024, 9, 2), date(2024, 9, 8))
        balance = leave.vacation_balance_id
        self.assertTrue(balance)
        # 2024-09-02 falls in work year 1 (2024-07-15 .. 2025-07-14).
        self.assertEqual(balance.period_start, date(2024, 7, 15))
        self.assertEqual(balance.period_end, date(2025, 7, 14))
        self.assertIn(balance, self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
        ]))

    def test_remaining_before_within_work_period(self):
        """Chronological remaining_before counts leaves linked to the same
        period even across a calendar-year boundary."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'entitled_days': 24,
        })
        first = self._create_leave(
            self.annual_type, date(2024, 10, 7), date(2024, 10, 13),
            vacation_balance_id=balance.id)
        second = self._create_leave(
            self.annual_type, date(2025, 2, 3), date(2025, 2, 9),
            vacation_balance_id=balance.id)
        self.assertEqual(first.remaining_days_before, 24)
        self.assertEqual(
            second.remaining_days_before, 24 - first.calendar_days)

    # ------------------------------------------------------------------
    # generate_balances
    # ------------------------------------------------------------------

    def test_generate_balances_work_type(self):
        Balance = self.env['hr.vacation.balance']
        Balance.generate_balances(
            year=date.today().year, leave_types=self.annual_type)
        balance = Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
        ], limit=1)
        self.assertTrue(balance)
        # Bounds anchored to July 15 anniversary, not Jan 1
        self.assertEqual(balance.period_start.month, 7)
        self.assertEqual(balance.period_start.day, 15)

    def test_generate_balances_calendar_type(self):
        Balance = self.env['hr.vacation.balance']
        year = date.today().year
        Balance.generate_balances(year=year, leave_types=self.social_type)
        balance = Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.social_type.id),
        ], limit=1)
        self.assertTrue(balance)
        self.assertEqual(balance.period_start, date(year, 1, 1))
        self.assertEqual(balance.period_end, date(year, 12, 31))

    def test_generate_balances_skips_employee_without_hire_date(self):
        Balance = self.env['hr.vacation.balance']
        nameless = self.env['hr.employee'].create({'name': 'Без дати найму'})
        Balance.generate_balances(
            year=date.today().year, leave_types=self.annual_type)
        balance = Balance.search([
            ('employee_id', '=', nameless.id),
            ('leave_type_id', '=', self.annual_type.id),
        ])
        self.assertFalse(balance)

    def test_generate_backfills_missing_periods_and_cascades(self):
        """generate_balances fills gaps from the hire date so carry-over
        cascades across a year that had no balance record (employee took no
        leave that year)."""
        Balance = self.env['hr.vacation.balance']
        # Only work year 1 exists, fully unused (24 days). WY2 is missing.
        wy1 = Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        self.assertEqual(wy1.remaining_days, 24)
        # Backfill from the hire date up to today's period, filling the WY2 gap
        # along the way (today may sit in WY2 or a later work year; either way
        # WY2 is created and its carry-over from WY1 is what we assert below).
        Balance.generate_balances(
            year=date.today().year, leave_types=self.annual_type)
        wy2 = Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
            ('period_start', '=', date(2025, 7, 15)),
        ])
        self.assertTrue(wy2, "Work year 2 should have been backfilled")
        # WY1's 24 unused days now carry into WY2 (annual is transferable).
        self.assertEqual(wy2.carried_over, 24)
        self.assertEqual(wy2.total_available, 48)

    def test_generate_only_for_auto_calc_types(self):
        """generate_balances (no explicit types) processes only leave types
        flagged with ua_auto_calc_balance."""
        Balance = self.env['hr.vacation.balance']
        # Make sure the type otherwise qualifies for the default selection
        # (transferable and day-accruing) so this test isolates the
        # ua_auto_calc_balance flag regardless of the type's stored config on
        # the database (which a persistent test DB may have altered).
        self.annual_type.write({'is_transferable': True, 'annual_days': 24})
        # Flag OFF -> nothing generated for this type (annual_basic ships
        # with the flag on, so turn it off explicitly for this assertion).
        self.annual_type.ua_auto_calc_balance = False
        Balance.generate_balances(year=date.today().year)
        self.assertFalse(Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
        ]))
        # Flag ON -> now its periods are generated.
        self.annual_type.ua_auto_calc_balance = True
        Balance.generate_balances(year=date.today().year)
        self.assertTrue(Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
        ]))

    def test_generate_uses_one_country_wide_leave_type(self):
        """Один вид відпустки обслуговує всі компанії країни.

        До Odoo 20 кожна компанія мала власний annual_basic, і генератор
        балансів мусив пропускати чужі пари «працівник — вид», інакше той
        самий період з'являвся двічі. У Odoo 20 hr.work.entry.type
        прив'язана до країни, тож вид один на всіх, а дубль неможливий
        за побудовою.
        """
        Balance = self.env['hr.vacation.balance']
        self.env['res.company'].create({'name': 'Company B'})
        lt = self.env['hr.work.entry.type'].create({
            'code': 'UA_T_VACATION_PER_1',
            'name': 'Annual country-wide',
            'ua_leave_category': 'annual_basic',
            'period_type': 'work',
            'annual_days': 24,
            'is_transferable': True,
            'ua_auto_calc_balance': True,
            'requires_allocation': False,
        })
        Balance.generate_balances(year=date.today().year, leave_types=lt)
        balances = Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', lt.id),
        ])
        self.assertTrue(balances, 'працівник має отримати періоди')
        self.assertEqual(len(balances.mapped('period_index')),
                         len(set(balances.mapped('period_index'))),
                         'жоден період не продубльовано')

    def test_generate_creates_no_overlapping_duplicates(self):
        """The backfill must not create a canonical period on top of an
        existing one whose start differs (legacy / differently-anchored row),
        which would look like a duplicate for the same span."""
        Balance = self.env['hr.vacation.balance']
        # Existing period with a non-canonical start (canonical WY2 starts
        # 2025-07-15) that still covers roughly work year 2.
        Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 9, 1),
            'period_end': date(2026, 8, 31),
            'entitled_days': 24,
        })
        Balance.generate_balances(
            year=date.today().year, leave_types=self.annual_type)
        rows = Balance.search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.annual_type.id),
        ], order='period_start')
        # No two periods may overlap.
        for a, b in zip(rows, rows[1:]):
            self.assertLess(
                a.period_end, b.period_start,
                'Generated periods must not overlap an existing one')

    def test_reanchor_period_after_hire_date_set(self):
        """A work-year balance created while the employee had no hire
        anchor gets calendar bounds; once hire_date is known, Recalculate
        re-anchors it to the hire anniversary."""
        employee = self.env['hr.employee'].create({'name': 'Пізній якір'})
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': employee.id,
            'leave_type_id': self.annual_type.id,
            'year': 2026,
            'entitled_days': 24,
        })
        # No anchor at creation time → calendar fallback
        self.assertEqual(balance.period_start, date(2026, 1, 1))
        self.assertEqual(balance.period_end, date(2026, 12, 31))

        employee.hire_date = date(2025, 7, 1)
        balance.action_recalculate()

        self.assertEqual(balance.period_start, date(2026, 7, 1))
        self.assertEqual(balance.period_end, date(2027, 6, 30))
        self.assertEqual(balance.period_index, 2)

    def test_balance_for_hire_year_uses_work_year_not_calendar(self):
        """A balance created by year only for an employee hired later in that
        same year resolves to the work year, not the calendar fallback.

        This is the transfer-wizard path: it carries vacation days over with
        just {'year': hire_date.year}, and for a future-dated hire the year's
        reference date lands before the hire anniversary.
        """
        employee = self.env['hr.employee'].create({'name': 'Transferred Employee'})
        version = employee.with_context(active_test=False).version_ids[:1]
        version.write({'contract_date_start': date(2050, 5, 1)})
        self.assertEqual(employee.hire_date, date(2050, 5, 1))

        balance = self.env['hr.vacation.balance'].create({
            'employee_id': employee.id,
            'leave_type_id': self.annual_type.id,
            'year': 2050,
            'entitled_days': 0,
            'carried_over': 7,
        })
        self.assertEqual(balance.period_start, date(2050, 5, 1))
        self.assertEqual(balance.period_end, date(2051, 4, 30))
        self.assertEqual(balance.period_index, 1)

    def test_reanchor_noop_when_already_correct(self):
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        balance.action_recalculate()
        self.assertEqual(balance.period_start, date(2024, 7, 15))
        self.assertEqual(balance.period_end, date(2025, 7, 14))

    def test_carryover_between_work_years(self):
        Balance = self.env['hr.vacation.balance']
        first = Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })
        self.assertEqual(first.remaining_days, 24)
        # Simulate the generator creating the next work year
        second = Balance.create({
            'employee_id': self.employee.id,
            'leave_type_id': self.annual_type.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
            'carried_over': first.remaining_days,
        })
        self.assertEqual(second.total_available, 48)

    # ------------------------------------------------------------------
    # Per-type transfer rules: carry-over cap + non-blocking warning
    # ------------------------------------------------------------------

    _work_type_seq = 0

    def _work_type(self, **overrides):
        # `code` is required and unique per country since Odoo 20.
        type(self)._work_type_seq += 1
        vals = {
            'code': 'UA_T_TRANSFER_%d' % self._work_type_seq,
            'name': 'Transfer Rule Type',
            'ua_leave_category': 'other',
            'period_type': 'work',
            'annual_days': 24,
            'is_transferable': True,
            'requires_allocation': False,
        }
        vals.update(overrides)
        return self.env['hr.work.entry.type'].create(vals)

    def _wy1_with_unused(self, leave_type):
        """A first work-year period (index 1) with 24 unused days."""
        return self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': leave_type.id,
            'period_start': date(2024, 7, 15),
            'period_end': date(2025, 7, 14),
            'period_index': 1,
            'entitled_days': 24,
        })

    def _wy2_of(self, leave_type):
        """Second work-year period (index 2), backfilled when the leave was
        created. The carry-over warning is derived from the leave dates, while
        carried_over lives on this period."""
        return self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', leave_type.id),
            ('period_index', '=', 2),
        ])

    def test_non_transferable_type_forfeits_and_warns(self):
        """A non-transferable type carries nothing forward; the leave still
        saves but shows a non-blocking warning about forfeited days."""
        lt = self._work_type(is_transferable=False)
        self._wy1_with_unused(lt)
        leave = self._create_leave(lt, date(2025, 9, 1), date(2025, 9, 5))
        wy2 = self._wy2_of(lt)
        self.assertTrue(wy2)
        self.assertEqual(wy2.carried_over, 0)          # nothing carried
        self.assertTrue(leave.carryover_warning)       # 24 days forfeited
        self.assertTrue(leave.id)                       # saved despite warning

    def test_capped_transfer_caps_and_warns(self):
        """max_transfer_days caps the carry-over; the excess is reported as a
        warning without blocking the save."""
        lt = self._work_type(is_transferable=True, max_transfer_days=10)
        self._wy1_with_unused(lt)
        leave = self._create_leave(lt, date(2025, 9, 1), date(2025, 9, 5))
        wy2 = self._wy2_of(lt)
        self.assertEqual(wy2.carried_over, 10)         # capped at the max
        self.assertTrue(leave.carryover_warning)       # 14 days forfeited

    def test_unlimited_transfer_no_warning(self):
        """A transferable type with no cap carries everything and warns of
        nothing."""
        lt = self._work_type(is_transferable=True)     # no max_transfer_days
        self._wy1_with_unused(lt)
        leave = self._create_leave(lt, date(2025, 9, 1), date(2025, 9, 5))
        wy2 = self._wy2_of(lt)
        self.assertEqual(wy2.carried_over, 24)         # everything carried
        self.assertFalse(leave.carryover_warning)

    def test_non_transferable_deficit_not_carried(self):
        """A non-transferable type carries nothing forward — not even a
        negative over-use debt. Its next period keeps Carried Over 0 and only
        its own entitlement, unlike a transferable type whose deficit rolls
        forward."""
        lt = self._work_type(is_transferable=False, leave_validation_type='hr')
        wy1 = self._wy1_with_unused(lt)                # entitled 24
        wy2 = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': lt.id,
            'period_start': date(2025, 7, 15),
            'period_end': date(2026, 7, 14),
            'period_index': 2,
            'entitled_days': 24,
        })
        # Over-use WY1: a leave longer than the entitlement, charged to WY1
        # and approved so the days count as used.
        leave = self._create_leave(
            lt, date(2024, 9, 1), date(2024, 9, 30), vacation_balance_id=wy1.id)
        leave.action_approve()
        self.assertGreater(wy1.used_days, 24)
        self.assertLess(wy1.remaining_days, 0)          # WY1 is in deficit
        wy2.invalidate_recordset(['carried_over', 'total_available'])
        self.assertEqual(wy2.carried_over, 0)           # debt NOT carried
        self.assertEqual(wy2.total_available, 24)       # only its own days
