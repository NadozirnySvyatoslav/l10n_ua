from datetime import datetime, date
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from odoo.tests import tagged

@tagged('post_install', '-at_install')
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
        
        cls.leave_type_calendar = cls.env['hr.leave.type'].create({
            'name': 'Annual Leave (Calendar) Test',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'company_id': cls.company.id,
            'requires_allocation': False,
        })
        
        cls.leave_type_working = cls.env['hr.leave.type'].create({
            'name': 'Other Leave (Working) Test',
            'ua_leave_category': 'other',
            'is_calendar_days': False,
            'is_paid': False,
            'company_id': cls.company.id,
            'requires_allocation': False,
        })

    def test_calendar_days_computation(self):
        """Test that calendar_days is computed correctly"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertGreater(leave.calendar_days, 0)

    def test_working_days_computation(self):
        """Test that working_days is computed correctly (Mon-Fri)"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
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
            'holiday_status_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
        })
        self.assertGreater(leave.number_of_days, 0)

    def test_vacation_pay_computation(self):
        """Test vacation pay calculation"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
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
            'holiday_status_id': self.leave_type_working.id,
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
            'year': 2028,
            'entitled_days': 24,
            'carried_over': 0,
        })
        
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'date_from': datetime(2028, 1, 15, 8, 0, 0),
            'date_to': datetime(2028, 1, 21, 17, 0, 0),
            'vacation_year': 2028,
        })
        
        self.assertGreaterEqual(leave.remaining_days_before, 0)
        self.assertLess(leave.remaining_days_after, leave.remaining_days_before)

    def test_order_fields(self):
        """Test order number and date fields"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
            'order_number': 'ORD-001',
            'order_date': date(2026, 1, 10),
        })
        self.assertEqual(leave.order_number, 'ORD-001')
        self.assertEqual(leave.order_date, date(2026, 1, 10))

    def test_vacation_year_field(self):
        """Test vacation year field"""
        leave = self.env['hr.leave'].create({
            'name': 'Test Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'date_from': datetime(2026, 1, 15, 8, 0, 0),
            'date_to': datetime(2026, 1, 21, 17, 0, 0),
            'vacation_year': 2025,
        })
        self.assertEqual(leave.vacation_year, 2025)

    def test_public_holidays_multiday_count(self):
        """_get_public_holidays_count() count days and not records
        one record resource.calendar.leaves on 3 days → 3, but not 1."""
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'New Year',
            'date_from': datetime(2035, 1, 1, 0, 0, 0),
            'date_to': datetime(2035, 1, 3, 23, 59, 59),
            'resource_id': False,
        })
        leave = self.env['hr.leave'].new({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'request_date_from': date(2035, 1, 1),
            'request_date_to': date(2035, 1, 7),
        })
        self.assertEqual(leave._get_public_holidays_count(), 3)
        holiday.unlink()

    def test_compute_duration_excludes_holidays(self):
        """7 calendar days, 1 holiday → number_of_days == 6."""
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Holiday',
            'date_from': datetime(2035, 3, 8, 0, 0, 0),
            'date_to': datetime(2035, 3, 8, 23, 59, 59),
            'resource_id': False,
        })
        leave = self.env['hr.leave'].create({
            'name': 'Test',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'request_date_from': date(2035, 3, 5),   # Mon
            'request_date_to': date(2035, 3, 11),    # Sun
            'date_from': datetime(2035, 3, 5, 8, 0, 0),
            'date_to': datetime(2035, 3, 11, 17, 0, 0),
        })
        self.assertEqual(leave.number_of_days, 6)  # 7 days − 1 holiday
        holiday.unlink()

    def test_working_days_excludes_public_holiday(self):
        """Mon-Fri (5 working days), one of them — holiday → working_days == 4."""
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Holiday',
            'date_from': datetime(2035, 4, 18, 0, 0, 0),  # Wednesday
            'date_to': datetime(2035, 4, 18, 23, 59, 59),
            'resource_id': False,
        })
        leave = self.env['hr.leave'].create({
            'name': 'Test',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'request_date_from': date(2035, 4, 16),  # Mon
            'request_date_to': date(2035, 4, 20),    # Fri
            'date_from': datetime(2035, 4, 16, 8, 0, 0),  # Mon
            'date_to': datetime(2035, 4, 20, 17, 0, 0),   # Fri
        })
        self.assertEqual(leave.working_days, 4)
        holiday.unlink()


    def test_remaining_before_fallback_no_balance_record(self):
        """_compute_remaining_before fallback: without hr.vacation.balance
        remaining_before = annual_days − already validated days in the year.
        """
        # Ensure no balance record exists for 2036
        self.env['hr.vacation.balance'].search([
            ('employee_id', '=', self.employee.id),
            ('leave_type_id', '=', self.leave_type_calendar.id),
            ('year', '=', 2036),
        ]).unlink()

        # Validated leave: Mon Feb 4 – Fri Feb 8, 2036 (5 days, no public holidays)
        used_leave = self.env['hr.leave'].create({
            'name': 'Used Leave',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'request_date_from': date(2036, 2, 4),   # Mon
            'request_date_to': date(2036, 2, 8),     # Fri
            'date_from': datetime(2036, 2, 4, 8, 0, 0),
            'date_to': datetime(2036, 2, 8, 17, 0, 0),
        })
        # Bypass workflow — set state directly
        used_leave.sudo()._write({'state': 'validate'})

        # In-memory record for 2036 — check remaining balance
        new_leave = self.env['hr.leave'].new({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type_calendar.id,
            'vacation_year': 2036,
        })
        new_leave._compute_remaining_before()

        # annual_days=24, 5 days used → 19 remaining
        self.assertEqual(new_leave.remaining_days_before, 19)

