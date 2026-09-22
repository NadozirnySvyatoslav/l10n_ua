from datetime import datetime, date
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestHrLeave(TransactionCase):
    """Tests for hr.leave Ukrainian extensions"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee Leave',
            'company_id': cls.company.id,
        })

        cls.leave_type_calendar = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_LEAVE_1',
            'name': 'Annual Leave (Calendar) Test',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
        })

        cls.leave_type_working = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_LEAVE_2',
            'name': 'Other Leave (Working) Test',
            'ua_leave_category': 'other',
            'is_calendar_days': False,
            'is_paid': False,
            'requires_allocation': False,
        })

    def test_calendar_days_computation(self):
        """Test that calendar_days is computed correctly"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertGreater(leave.calendar_days, 0)

    def test_working_days_computation(self):
        """Test that working_days is computed correctly (Mon-Fri)"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'request_date_from': date(2026, 1, 15),
            'request_date_to':   date(2026, 1, 21),
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertGreater(leave.working_days, 0)
        self.assertLessEqual(leave.working_days, leave.calendar_days)

    def test_number_of_days_calendar_type(self):
        """Test that number_of_days uses calendar days for is_calendar_days=True"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertGreater(leave.number_of_days, 0)

    def test_vacation_pay_computation(self):
        """Test vacation pay calculation"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
            'average_daily_salary': 500.0,
        })
        self.assertGreaterEqual(leave.vacation_pay_amount, 0)

    def test_vacation_pay_unpaid_leave(self):
        """Test that unpaid leave has zero vacation pay"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_working.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
            'average_daily_salary': 500.0,
        })
        self.assertEqual(leave.vacation_pay_amount, 0.0)

    def test_remaining_days_after_computation(self):
        """Test remaining_days_after calculation"""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type_calendar.id,
            'period_start': date(2028, 1, 1),
            'period_end': date(2028, 12, 31),
            'entitled_days': 24,
            'carried_over': 0,
            'company_id': self.company.id,
        })

        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'request_date_from': date(2028, 1, 15),
            'request_date_to': date(2028, 1, 21),
            'date_from': datetime(2028, 1, 15, 8, 0, 0),
            'date_to': datetime(2028, 1, 21, 17, 0, 0),
            'vacation_balance_id': balance.id,
        })

        self.assertGreaterEqual(leave.remaining_days_before, 0)
        self.assertLess(leave.remaining_days_after, leave.remaining_days_before)

    def test_order_fields(self):
        """Test order number and date fields"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
            'order_number': 'ORD-001',
            'order_date': date(2026, 1, 10),
        })
        self.assertEqual(leave.order_number, 'ORD-001')
        self.assertEqual(leave.order_date, date(2026, 1, 10))

    def test_vacation_year_field(self):
        """Vacation year is read-only and follows the leave start date."""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            # vacation_year follows request_date_from (the driver field), so
            # set it explicitly rather than relying on date_from back-derivation.
            'request_date_from': date(2026, 1, 15),
            'request_date_to': date(2026, 1, 21),
            'vacation_year': 2025,  # ignored — the field is computed
        })
        self.assertEqual(leave.vacation_year, 2026)
        # Odoo 20 auto-approves what a Time Off Officer creates, and an
        # approved leave refuses date changes — put it back to "To Approve".
        if leave.state == 'validate':
            leave.sudo().state = 'confirm'
        # Moving the dates re-derives the year automatically.
        leave.write({
            'request_date_from': date(2027, 3, 1),
            'request_date_to': date(2027, 3, 5),
        })
        self.assertEqual(leave.vacation_year, 2027)


    def test_default_leave_type_preselected(self):
        """When creating a leave without specifying type, default is preselected."""
        # Set leave_type_calendar as the company default
        self.env.company.l10n_ua_default_leave_type_id = self.leave_type_calendar
        # Create leave without specifying work_entry_type_id
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertEqual(leave.work_entry_type_id, self.leave_type_calendar)

    def test_vacation_period_auto_selected(self):
        """When creating a leave, the period its first day falls into is
        auto-selected if it already exists (no duplicate)."""
        # Pre-create the 2026 period; the leave's first day (2026-06-15) falls
        # into it, so it must be reused rather than duplicated.
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type_calendar.id,
            'period_start': date(2026, 1, 1),
            'period_end': date(2026, 12, 31),
            'entitled_days': 24,
            'company_id': self.company.id,
        })
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'request_date_from': date(2026, 6, 15),
            'request_date_to': date(2026, 6, 21),
            'date_from': datetime(2026, 6, 15, 8, 0, 0),
            'date_to': datetime(2026, 6, 21, 17, 0, 0),
        })
        self.assertEqual(leave.vacation_balance_id, balance)

    def test_vacation_period_auto_created_on_create(self):
        """Creating a leave with no chosen period auto-creates and links the
        period the leave's FIRST DAY falls into (a future 2029 period here),
        and it lands in hr.vacation.balance / Vacation Balances."""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'request_date_from': date(2029, 6, 15),
            'request_date_to': date(2029, 6, 21),
            'date_from': datetime(2029, 6, 15, 8, 0, 0),
            'date_to': datetime(2029, 6, 21, 17, 0, 0),
        })
        self.assertTrue(leave.vacation_balance_id)
        # Defaults to the period the first vacation day falls into (2029).
        self.assertEqual(
            leave.vacation_balance_id.period_start, date(2029, 1, 1))
        self.assertEqual(
            leave.vacation_balance_id.period_end, date(2029, 12, 31))
        # The period is a real hr.vacation.balance record (Vacation Balances).
        self.assertIn(leave.vacation_balance_id, self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.leave_type_calendar.id),
        ]))

    def test_vacation_period_kept_on_date_change(self):
        """The accounting period is a manual choice: moving the leave dates to
        another year does NOT re-point the leave at a different period."""
        today = date.today()
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type_calendar.id,
            'period_start': date(today.year, 1, 1),
            'period_end': date(today.year, 12, 31),
            'entitled_days': 24,
            'company_id': self.company.id,
        })
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type_calendar.id,
            'request_date_from': date(today.year, 6, 15),
            'request_date_to': date(today.year, 6, 21),
            'date_from': datetime(today.year, 6, 15, 8, 0, 0),
            'date_to': datetime(today.year, 6, 21, 17, 0, 0),
        })
        # Defaults to the current period on create.
        self.assertEqual(leave.vacation_balance_id, balance)
        # Odoo 20 auto-approves what a Time Off Officer creates, and an
        # approved leave refuses date changes — put it back to "To Approve".
        if leave.state == 'validate':
            leave.sudo().state = 'confirm'
        # Moving to 2030 leaves the chosen period untouched.
        leave.write({
            'request_date_from': date(2030, 6, 15),
            'request_date_to': date(2030, 6, 21),
            'date_from': datetime(2030, 6, 15, 8, 0, 0),
            'date_to': datetime(2030, 6, 21, 17, 0, 0),
        })
        self.assertEqual(leave.vacation_balance_id, balance)
