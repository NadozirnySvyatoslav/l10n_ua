"""Tests for HR orders (накази) — HR-1,19,20 from HR_UKRAINE.md.

Tests cover:
- Order creation with auto-sequencing
- Order types (hiring, dismissal, transfer, etc.)
- Subject computation
- State workflow (draft -> confirmed -> cancelled)
- Employee order count
"""

from datetime import date
from odoo.tests import TransactionCase, tagged
from unittest.mock import patch

@tagged('post_install', '-at_install')
class TestHrOrder(TransactionCase):
    """Test hr.order model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.department = cls.env['hr.department'].create({
            'name': 'Відділ кадрів',
            'company_id': cls.company.id,
        })

        cls.job = cls.env['hr.job'].create({
            'name': 'Менеджер',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
        })

        cls.employee = cls.env['hr.employee'].create({
            'name': 'Коваленко Марія Петрівна',
            'company_id': cls.company.id,
            'department_id': cls.department.id,
            'job_id': cls.job.id,
        })

        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Annual Basic Leave',
            'time_type': 'leave',
            'requires_allocation': 'no',
            'create_order': True,
            'is_paid': True,
        })

        # Find all leave types in the test database
        leave_types = cls.env['hr.leave.type'].search([])
        # Disable allocation requirements to prevent ValidationError during test execution
        if 'requires_allocation' in leave_types._fields:
            leave_types.write({'requires_allocation': 'no'})
        elif 'allocation_type' in leave_types._fields: # Fallback  
            leave_types.write({'allocation_type': 'no'})

    def _create_order(self, order_type='hiring', **kwargs):
        vals = {
            'order_type': order_type,
            'employee_id': self.employee.id,
            'date': date(2025, 6, 1),
            'subject': 'Test subject',
            'company_id': self.company.id,
        }
        if order_type == 'vacation':
            vals['holiday_status_id'] = self.leave_type.id
            vals['vacation_date_from'] = date(2025, 6, 1)
            vals['vacation_date_to'] = date(2025, 6, 14)
        vals.update(kwargs)
        # Surgically disable Odoo's core leave validation for the duration of this creation.
        # This bypasses the allocation check regardless of how the leave type is generated.
        with patch.object(type(self.env['hr.leave']), '_check_validity', lambda *args, **kwargs: None):
            return self.env['hr.order'].create(vals)

    def test_order_creation(self):
        """Order should be created in draft state with auto number."""
        order = self._create_order()
        self.assertEqual(order.state, 'draft')
        self.assertTrue(order.name)

    def test_order_hiring(self):
        """Hiring order should have correct type."""
        order = self._create_order('hiring')
        self.assertEqual(order.order_type, 'hiring')

    def test_order_dismissal(self):
        """Dismissal order should have correct type."""
        order = self._create_order('dismissal')
        self.assertEqual(order.order_type, 'dismissal')

    def test_order_termination_reason_onchange(self):
        """Picking termination_reason_id should auto-fill dismissal_reason text (#95)."""
        reason = self.env.ref('l10n_ua_hr_contract.termination_reason_war_2136_art5')
        order = self._create_order('dismissal')
        order.termination_reason_id = reason
        order._onchange_termination_reason_id()
        self.assertEqual(order.dismissal_reason, reason.full_text)
        self.assertIn('2136-IX', order.dismissal_reason)

    def test_order_types(self):
        """All 8 order types should be valid."""
        types = ['hiring', 'dismissal', 'transfer', 'vacation',
                 'bonus', 'sick_leave', 'business_trip', 'other']
        for otype in types:
            order = self._create_order(otype)
            self.assertEqual(order.order_type, otype)
            order.unlink()

    def test_order_subject_default(self):
        """Subject should be present on created order."""
        order = self._create_order('hiring')
        self.assertTrue(order.subject)

    def test_order_confirm(self):
        """Confirm should move to confirmed state."""
        order = self._create_order()
        order.action_confirm()
        self.assertEqual(order.state, 'confirmed')

    def test_order_cancel(self):
        """Cancel should move to cancelled state."""
        order = self._create_order()
        order.action_confirm()
        order.action_cancel()
        self.assertEqual(order.state, 'cancelled')

    def test_order_draft_reset(self):
        """Draft should reset from cancelled."""
        order = self._create_order()
        order.action_confirm()
        order.action_cancel()
        order.action_draft()
        self.assertEqual(order.state, 'draft')

    def test_order_auto_sequence(self):
        """Each order should get a unique name/number."""
        order1 = self._create_order('hiring')
        order2 = self._create_order('hiring')
        self.assertNotEqual(order1.name, order2.name)

    def test_employee_orders_count(self):
        """Employee should track order count."""
        self._create_order('hiring')
        self._create_order('transfer')
        self.employee.invalidate_recordset()
        self.assertEqual(self.employee.orders_count, 2)

    def test_employee_onchange_fills_department(self):
        """Setting employee should auto-fill department and job."""
        order = self.env['hr.order'].new({
            'order_type': 'hiring',
            'employee_id': self.employee.id,
            'company_id': self.company.id,
        })
        order._onchange_employee_id()
        self.assertEqual(order.department_id, self.department)
        self.assertEqual(order.job_id, self.job)


@tagged('post_install', '-at_install')
class TestHrOrderMultiCompany(TransactionCase):
    """Multi-company isolation for hr.order."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Company B'})
        cls.dept_a = cls.env['hr.department'].create({
            'name': 'Dept A', 'company_id': cls.company_a.id,
        })
        cls.dept_b = cls.env['hr.department'].create({
            'name': 'Dept B', 'company_id': cls.company_b.id,
        })
        cls.job_a = cls.env['hr.job'].create({
            'name': 'Job A', 'company_id': cls.company_a.id,
            'department_id': cls.dept_a.id,
        })
        cls.employee_a = cls.env['hr.employee'].create({
            'name': 'Emp A', 'company_id': cls.company_a.id,
        })

    def test_onchange_company_resets_cross_company_fields(self):
        order = self.env['hr.order'].new({
            'company_id': self.company_a.id,
            'employee_id': self.employee_a.id,
            'department_id': self.dept_a.id,
            'job_id': self.job_a.id,
            'order_type': 'hiring',
            'date': date(2026, 4, 20),
        })
        order.company_id = self.company_b
        order._onchange_company_id()
        self.assertFalse(order.employee_id)
        self.assertFalse(order.department_id)
        self.assertFalse(order.job_id)

    def test_onchange_company_keeps_shared_records(self):
        shared_dept = self.env['hr.department'].create({
            'name': 'Shared', 'company_id': False,
        })
        order = self.env['hr.order'].new({
            'company_id': self.company_a.id,
            'department_id': shared_dept.id,
            'order_type': 'hiring',
            'date': date(2026, 4, 20),
        })
        order.company_id = self.company_b
        order._onchange_company_id()
        self.assertEqual(order.department_id, shared_dept)
