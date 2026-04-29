from odoo.tests import common
from datetime import date
from odoo.tests import tagged

@tagged('post_install', '-at_install')
class TestHrLeaveOrderSync(common.TransactionCase):
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Create a test employee
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Test Employee',
        })
        
        # Create a leave type that generates orders
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Annual Basic Leave',
            'time_type': 'leave',
            'requires_allocation': 'yes',
            'create_order': True,
            'is_paid': True,
        })

        # Allocate leave days to the employee so validation passes
        cls.allocation = cls.env['hr.leave.allocation'].create({
            'name': 'Test Leave Allocation',
            'employee_id': cls.employee.id,
            'holiday_status_id': cls.leave_type.id,
            'number_of_days': 100,
        })
        cls.allocation.action_approve()
        if cls.allocation.state == 'validate1':
            cls.allocation.action_validate()

    def test_bidirectional_create_from_order(self):
        """ Test: Creating an order creates exactly 1 leave and does not duplicate orders. """
        order = self.env['hr.order'].create({
            'order_type': 'vacation',
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'vacation_date_from': date(2027, 8, 1),
            'vacation_date_to': date(2027, 8, 5),
            'date': date(2027, 8, 1),
            'subject': 'Vacation',
        })
        
        # Check that there is only one order
        orders_count = self.env['hr.order'].search_count([('employee_id', '=', self.employee.id)])
        self.assertEqual(orders_count, 1, "Order creation generated a duplicate.")
        
        # Check that there is only one leave
        leaves = self.env['hr.leave'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(leaves), 1, "Exactly one leave must be created.")
        
        # Check bidirectional relationship
        self.assertEqual(order.leave_id.id, leaves.id)
        self.assertEqual(leaves.order_id.id, order.id)

    def test_bidirectional_create_from_leave(self):
        """ Test: Creating a leave creates exactly 1 order. """
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': date(2027, 9, 1),
            'request_date_to': date(2027, 9, 5),
        })
        
        orders = self.env['hr.order'].search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(orders), 1, "Exactly one order must be created.")
        self.assertEqual(leave.order_id.id, orders.id)

    def test_state_sync_validate(self):
        """ Test: Validating a leave confirms the order. """
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': date(2027, 10, 1),
            'request_date_to': date(2027, 10, 5),
        })
        
        order = leave.order_id
        self.assertEqual(order.state, 'draft')
        
        # Call the private hook or standard action_approve
        leave._action_validate()
        
        self.assertEqual(order.state, 'confirmed', "Order state did not change to confirmed after leave validation.")

    def test_cascade_delete(self):
        """ Test: Unlinking a draft leave also unlinks the draft order. """
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': self.leave_type.id,
            'request_date_from': date(2027, 11, 1),
            'request_date_to': date(2027, 11, 5),
        })
        
        order = leave.order_id
        self.assertTrue(order.exists())
        
        leave.unlink()
        
        self.assertFalse(order.exists(), "The order was not cascade deleted with the leave.")
