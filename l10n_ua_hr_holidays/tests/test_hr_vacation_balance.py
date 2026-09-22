from datetime import datetime
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestHrVacationBalance(TransactionCase):
    """Tests for hr.vacation.balance model"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee Balance',
            'company_id': cls.company.id,
        })
        
        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_VACATION__1',
            'name': 'Annual Leave Balance Test',
            'ua_leave_category': 'annual_basic',
            'is_calendar_days': True,
            'annual_days': 24,
            'is_paid': True,
            'requires_allocation': False,
        })

    def test_balance_creation(self):
        """Test vacation balance creation"""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2030,
            'entitled_days': 24,
            'carried_over': 5,
        })
        self.assertEqual(balance.entitled_days, 24)
        self.assertEqual(balance.carried_over, 5)
        self.assertEqual(balance.total_available, 29)
        self.assertEqual(balance.remaining_days, 29)

    def test_total_available_computation(self):
        """Test total_available = entitled_days + carried_over"""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2031,
            'entitled_days': 24,
            'carried_over': 10,
        })
        self.assertEqual(balance.total_available, 34)

    def test_remaining_days_computation(self):
        """Test remaining_days = total_available - used_days"""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2032,
            'entitled_days': 24,
            'carried_over': 0,
        })
        
        self.assertEqual(balance.total_available, 24)
        self.assertEqual(balance.remaining_days, 24)

    def test_used_days_initial(self):
        """Test that initial used_days is 0"""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2033,
            'entitled_days': 24,
            'carried_over': 0,
        })
        
        self.assertEqual(balance.used_days, 0)
        self.assertEqual(balance.planned_days, 0)

    def test_display_name(self):
        """Display name is the period only (employee shown elsewhere)."""
        balance = self.env['hr.vacation.balance'].create({
            'employee_id': self.employee.id,
            'leave_type_id': self.leave_type.id,
            'year': 2034,
            'entitled_days': 24,
        })
        self.assertEqual(balance.display_name, balance.period_label)
        self.assertNotIn(self.employee.name, balance.display_name)

    def test_unique_constraint(self):
        """Test unique constraint on employee + leave type + period exists.

        The full name (hr_vacation_balance_unique_employee_id_leave_type_id_
        period_start) exceeds PostgreSQL's 63-char identifier limit, so it is
        truncated and hashed; match by the stable prefix instead of the exact
        (untruncated) name."""
        constraint = self.env['ir.model.constraint'].search([
            ('name', 'like',
             'hr_vacation_balance_unique_employee_id_leave_type_id_p%'),
        ])
        self.assertTrue(constraint, "Unique constraint should exist on hr.vacation.balance")
