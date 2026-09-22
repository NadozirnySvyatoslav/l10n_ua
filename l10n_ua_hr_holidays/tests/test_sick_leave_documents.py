"""Sick leave issues its documents through explicit buttons (#158).

Confirming a sick leave used to create the absence in the background and
approve it on the spot — no author, no trail, and the approval gate of
hr_holidays skipped. The certificate, the absence and the order are three
documents now, each created by whoever has the right to create it, the same
way #217 reworked the vacation flow.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSickLeaveDocuments(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Хворий Працівник',
        })
        cls.sick_leave = cls.env['hr.sick.leave'].create({
            'employee_id': cls.employee.id,
            'date_from': date(2026, 3, 2),
            'date_to': date(2026, 3, 10),
            'sick_leave_type': 'illness',
        })

    def test_confirm_creates_no_documents(self):
        """Confirming only moves the certificate's own state."""
        self.sick_leave.action_confirm()
        self.assertEqual(self.sick_leave.state, 'confirmed')
        self.assertFalse(self.sick_leave.leave_id)
        self.assertFalse(self.sick_leave.order_id)
        self.assertFalse(self.env['hr.leave'].search([
            ('employee_id', '=', self.employee.id),
        ]))

    def test_leave_button_prefills_and_links_back(self):
        action = self.sick_leave.action_create_leave()
        ctx = action['context']
        self.assertEqual(ctx['default_employee_id'], self.employee.id)
        self.assertEqual(ctx['default_request_date_from'], date(2026, 3, 2))
        self.assertEqual(ctx['default_request_date_to'], date(2026, 3, 10))
        self.assertEqual(ctx['default_sick_leave_id'], self.sick_leave.id)

        # Nothing exists until the user saves the pre-filled form.
        self.assertFalse(self.sick_leave.leave_id)

        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': ctx['default_work_entry_type_id'],
            'request_date_from': date(2026, 3, 2),
            'request_date_to': date(2026, 3, 10),
            'sick_leave_id': self.sick_leave.id,
        })
        self.assertEqual(self.sick_leave.leave_id, leave)
        # The absence goes through the ordinary approval flow. Odoo 20 hands
        # a Time Off Officer's own request straight to "Approved"
        # (_process_auto_approve_activities); anyone else still has to have
        # it approved.
        self.assertIn(leave.state, ('draft', 'confirm', 'validate'))

    def test_leave_button_blocked_when_one_exists(self):
        self.sick_leave.leave_id = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.sick_leave._sick_leave_type().id,
            'request_date_from': date(2026, 3, 2),
            'request_date_to': date(2026, 3, 10),
        })
        self.assertFalse(self.sick_leave.can_create_leave)
        with self.assertRaises(UserError):
            self.sick_leave.action_create_leave()

    def test_order_button_prefills_and_links_back(self):
        action = self.sick_leave.action_create_order()
        ctx = action['context']
        self.assertEqual(ctx['default_order_type'], 'sick_leave')
        self.assertEqual(ctx['default_sick_leave_id'], self.sick_leave.id)
        self.assertFalse(self.sick_leave.order_id)

        order = self.env['hr.order'].with_context(**ctx).create({
            'subject': 'Про оплату листка непрацездатності',
            'employee_id': self.employee.id,
            'order_type': 'sick_leave',
            'date': date(2026, 3, 11),
        })
        self.assertEqual(order.sick_leave_id, self.sick_leave)
        self.assertEqual(self.sick_leave.order_id, order)
        self.assertFalse(self.sick_leave.can_create_order)

    def test_order_button_blocked_when_one_exists(self):
        self.sick_leave.order_id = self.env['hr.order'].create({
            'subject': 'Про оплату листка непрацездатності',
            'employee_id': self.employee.id,
            'order_type': 'sick_leave',
            'date': date(2026, 3, 11),
        })
        with self.assertRaises(UserError):
            self.sick_leave.action_create_order()
