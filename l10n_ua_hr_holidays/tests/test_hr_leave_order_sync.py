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

        cls.leave_type = cls.env['hr.work.entry.type'].create({
            'code': 'UA_T_HR_LEAVE_ORD_1',
            'name': 'Annual Basic Leave',
            'count_as': 'absence',
            'requires_allocation': 'yes',
            'is_paid': True,
        })

        # Allocate leave days to the employee so validation passes
        cls.allocation = cls.env['hr.leave.allocation'].create({
            'name': 'Test Leave Allocation',
            'employee_id': cls.employee.id,
            'work_entry_type_id': cls.leave_type.id,
            'number_of_days': 100,
        })
        cls.allocation.action_approve()
        if cls.allocation.state == 'validate1':
            cls.allocation.action_validate()

    def _make_leave(self, day_from, day_to):
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type.id,
            'request_date_from': day_from,
            'request_date_to': day_to,
        })
        # Odoo 20 auto-approves a leave created by a Time Off Officer
        # (hr_holidays._process_auto_approve_activities), and the tests run
        # as admin. These cases are about a leave still being edited, so put
        # it back to "To Approve".
        if leave.state == 'validate':
            leave.sudo().state = 'confirm'
        return leave

    def _create_order_via_button(self, leave):
        """Simulate the 'Create Order' button: it returns an action opening a
        pre-filled order form; here we replay the form save by creating the
        order from the action's default_* context."""
        ctx = leave.action_create_order()['context']
        return self.env['hr.order'].create({
            'order_type': ctx['default_order_type'],
            'employee_id': ctx['default_employee_id'],
            'department_id': ctx['default_department_id'],
            'job_id': ctx['default_job_id'],
            'leave_id': ctx['default_leave_id'],
            'vacation_date_from': ctx['default_vacation_date_from'],
            'vacation_date_to': ctx['default_vacation_date_to'],
            'subject': ctx['default_subject'],
        })

    def _make_vacation_order(self, day_from, day_to, **extra):
        vals = {
            'order_type': 'vacation',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type.id,
            'vacation_date_from': day_from,
            'vacation_date_to': day_to,
            'date': day_from,
            'subject': 'Vacation',
        }
        vals.update(extra)
        return self.env['hr.order'].create(vals)

    def _create_leave_via_button(self, order):
        """Simulate the "New Time Off" button: it returns an action opening a
        pre-filled leave form; here we replay the form save."""
        ctx = order.action_create_leave()['context']
        return self.env['hr.leave'].create({
            'employee_id': ctx['default_employee_id'],
            'work_entry_type_id': ctx['default_work_entry_type_id'],
            'request_date_from': ctx['default_request_date_from'],
            'request_date_to': ctx['default_request_date_to'],
            'order_id': ctx['default_order_id'],
        })

    def test_no_leave_created_on_order_save(self):
        """Saving a vacation order must NOT auto-create the time off."""
        order = self._make_vacation_order(date(2027, 8, 1), date(2027, 8, 5))

        self.assertFalse(order.leave_id,
                         "Saving an order should not create a leave.")
        self.assertEqual(self.env['hr.leave'].search_count(
            [('employee_id', '=', self.employee.id)]), 0)
        self.assertTrue(order.can_create_leave,
                        "The 'New Time Off' button should be available.")

    def test_new_time_off_button_prefills_and_links(self):
        """The button opens a leave form pre-filled from the order; saving it
        links both sides."""
        order = self._make_vacation_order(date(2027, 8, 1), date(2027, 8, 5))
        action = order.action_create_leave()

        self.assertEqual(action['res_model'], 'hr.leave')
        self.assertEqual(action['view_mode'], 'form')
        ctx = action['context']
        self.assertEqual(ctx['default_employee_id'], self.employee.id)
        self.assertEqual(ctx['default_work_entry_type_id'], self.leave_type.id)
        self.assertEqual(ctx['default_request_date_from'], date(2027, 8, 1))
        self.assertEqual(ctx['default_request_date_to'], date(2027, 8, 5))
        self.assertEqual(ctx['default_order_id'], order.id)
        # Nothing exists until the user saves.
        self.assertFalse(order.leave_id)

        leave = self._create_leave_via_button(order)

        self.assertEqual(leave.order_id, order)
        self.assertEqual(order.leave_id, leave, "The order must point back.")
        self.assertFalse(order.can_create_leave,
                         "Button must hide once a leave exists.")
        self.assertEqual(self.env['hr.leave'].search_count(
            [('employee_id', '=', self.employee.id)]), 1,
            "No duplicate leave must be created.")

    def test_leave_keeps_the_order_when_the_form_drops_it(self):
        """The link survives even if the form loses order_id — navigating away
        from the unsaved leave and back would otherwise save it unlinked and
        let the order offer a second one."""
        order = self._make_vacation_order(date(2027, 8, 20), date(2027, 8, 25))
        ctx = order.action_create_leave()['context']

        # Save WITHOUT order_id, as a form that lost the default would.
        leave = self.env['hr.leave'].with_context(**ctx).create({
            'employee_id': ctx['default_employee_id'],
            'work_entry_type_id': ctx['default_work_entry_type_id'],
            'request_date_from': ctx['default_request_date_from'],
            'request_date_to': ctx['default_request_date_to'],
        })

        self.assertEqual(leave.order_id, order,
                         'The context must still link the leave to its order.')
        self.assertEqual(order.leave_id, leave)
        self.assertFalse(order.can_create_leave)

    def test_order_keeps_the_leave_when_the_form_drops_it(self):
        """Same protection in the other direction."""
        leave = self._make_leave(date(2027, 8, 20), date(2027, 8, 25))
        ctx = leave.action_create_order()['context']

        order = self.env['hr.order'].with_context(**ctx).create({
            'order_type': ctx['default_order_type'],
            'employee_id': ctx['default_employee_id'],
            'vacation_date_from': ctx['default_vacation_date_from'],
            'vacation_date_to': ctx['default_vacation_date_to'],
            'subject': ctx['default_subject'],
        })

        self.assertEqual(order.leave_id, leave,
                         'The context must still link the order to its leave.')
        self.assertFalse(leave.can_create_order)

    def test_new_time_off_blocked_when_leave_exists(self):
        """Calling the button twice must not start a second leave."""
        from odoo.exceptions import UserError
        order = self._make_vacation_order(date(2027, 8, 10), date(2027, 8, 15))
        self._create_leave_via_button(order)
        with self.assertRaises(UserError):
            order.action_create_leave()

    def test_no_order_created_on_save(self):
        """Saving a leave must NOT auto-create an order anymore."""
        leave = self._make_leave(date(2027, 9, 1), date(2027, 9, 5))
        self.assertFalse(leave.order_id, "Saving a leave should not create an order.")
        orders = self.env['hr.order'].search(
            [('employee_id', '=', self.employee.id)])
        self.assertEqual(len(orders), 0, "No order should exist after saving a leave.")
        self.assertTrue(leave.can_create_order,
                        "The 'Create Order' button should be available.")

    def test_manual_create_order_action(self):
        """The button returns an action opening the order form pre-filled from
        the leave, and does NOT create the order itself."""
        leave = self._make_leave(date(2027, 9, 10), date(2027, 9, 15))
        action = leave.action_create_order()

        self.assertEqual(action['res_model'], 'hr.order')
        self.assertEqual(action['view_mode'], 'form')
        ctx = action['context']
        self.assertEqual(ctx['default_leave_id'], leave.id)
        self.assertEqual(ctx['default_employee_id'], self.employee.id)
        self.assertEqual(ctx['default_order_type'], 'vacation')
        self.assertEqual(ctx['default_vacation_date_from'], date(2027, 9, 10))
        self.assertEqual(ctx['default_vacation_date_to'], date(2027, 9, 15))

        # Nothing is created until the user saves the form.
        self.assertFalse(leave.order_id)
        self.assertEqual(self.env['hr.order'].search_count(
            [('employee_id', '=', self.employee.id)]), 0)

    def test_manual_create_order_saved_links_no_duplicate(self):
        """Saving the pre-filled order links it to the leave as a draft and
        does not spawn a second leave or order."""
        leave = self._make_leave(date(2027, 9, 10), date(2027, 9, 15))
        order = self._create_order_via_button(leave)

        self.assertEqual(order.state, 'draft',
                         "Order for an unapproved leave must be a draft.")
        self.assertEqual(order.leave_id, leave)
        self.assertEqual(leave.order_id, order)
        self.assertFalse(leave.can_create_order,
                         "Button must hide once an order exists.")
        self.assertEqual(leave.order_count, 1)
        self.assertEqual(self.env['hr.leave'].search_count(
            [('employee_id', '=', self.employee.id)]), 1,
            "No duplicate leave must be created.")
        self.assertEqual(self.env['hr.order'].search_count([
            ('employee_id', '=', self.employee.id),
            ('order_type', '=', 'vacation'),
        ]), 1, "No duplicate order must be created.")

    def test_smart_buttons_scoped_to_this_document(self):
        """The Orders / Time Off smart buttons count and open the documents
        linked to THIS record — a second leave with its own order must not
        inflate the first one's count."""
        leave_a = self._make_leave(date(2028, 5, 10), date(2028, 5, 15))
        order_a = self._create_order_via_button(leave_a)
        leave_b = self._make_leave(date(2028, 8, 10), date(2028, 8, 15))
        order_b = self._create_order_via_button(leave_b)

        # The employee has two vacation orders overall...
        self.assertEqual(self.env['hr.order'].search_count([
            ('employee_id', '=', self.employee.id),
            ('order_type', '=', 'vacation'),
        ]), 2)

        # ...but each leave sees only its own.
        (leave_a | leave_b).invalidate_recordset(['order_count'])
        self.assertEqual(leave_a.order_count, 1)
        self.assertEqual(leave_b.order_count, 1)
        self.assertEqual(leave_a.action_view_orders().get('res_id'), order_a.id)
        self.assertEqual(leave_b.action_view_orders().get('res_id'), order_b.id)

        # Same scoping from the order side.
        (order_a | order_b).invalidate_recordset(['leave_count'])
        self.assertEqual(order_a.leave_count, 1)
        self.assertEqual(order_a.action_view_leaves().get('res_id'), leave_a.id)
        self.assertEqual(order_b.action_view_leaves().get('res_id'), leave_b.id)

    def test_button_blocked_when_order_exists(self):
        """Once an order is linked, the button raises instead of starting a
        second one."""
        leave = self._make_leave(date(2027, 9, 20), date(2027, 9, 25))
        self._create_order_via_button(leave)
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            leave.action_create_order()

    def test_manual_order_date_sync(self):
        """Editing the leave dates flows through to the linked draft order."""
        leave = self._make_leave(date(2027, 10, 10), date(2027, 10, 15))
        order = self._create_order_via_button(leave)

        leave.write({
            'request_date_from': date(2027, 10, 12),
            'request_date_to': date(2027, 10, 18),
        })
        self.assertEqual(order.vacation_date_from, date(2027, 10, 12))
        self.assertEqual(order.vacation_date_to, date(2027, 10, 18))

    def test_validation_never_issues_an_order(self):
        """Approving a leave issues no order — orders come only from the
        "New Order" button."""
        leave = self._make_leave(date(2027, 10, 1), date(2027, 10, 5))
        self.assertFalse(leave.order_id)

        leave._action_validate()

        self.assertFalse(leave.order_id,
                         "Approving a leave must not create an order.")
        self.assertEqual(self.env['hr.order'].search_count([
            ('employee_id', '=', self.employee.id),
            ('order_type', '=', 'vacation'),
        ]), 0)

    def test_validation_leaves_existing_draft_untouched(self):
        """A draft order keeps its state when its leave is approved: only the
        order's own buttons move it."""
        leave = self._make_leave(date(2027, 11, 10), date(2027, 11, 15))
        draft = self._create_order_via_button(leave)
        self.assertEqual(draft.state, 'draft')

        leave._action_validate()

        self.assertEqual(leave.order_id, draft, "Order must not be replaced.")
        self.assertEqual(draft.state, 'draft',
                         "Approving the leave must not confirm the order.")

    def test_order_confirm_does_not_approve_leave(self):
        """Confirming a vacation order does not move the leave: states are
        changed only through their own buttons. The leave can still be
        approved afterwards, when the order was issued first."""
        order = self._make_vacation_order(date(2028, 3, 1), date(2028, 3, 5))
        leave = self._create_leave_via_button(order)
        state_before = leave.state

        order.action_confirm()

        self.assertEqual(order.state, 'confirmed')
        self.assertEqual(leave.state, state_before,
                         "Confirming the order must not move the leave.")

        # Approving the leave later is still allowed — the whole point of
        # keeping Approve active once an order exists.
        leave._action_validate()
        self.assertEqual(leave.state, 'validate')

    def test_confirmed_order_blocks_undoing_the_leave(self):
        """A confirmed order is the legal document obliging the employee to
        take the leave, so the leave can no longer be refused or sent back to
        approval."""
        from odoo.exceptions import UserError
        leave = self._make_leave(date(2028, 9, 1), date(2028, 9, 5))
        order = self._create_order_via_button(leave)
        order.action_confirm()
        leave.invalidate_recordset(['has_confirmed_order'])
        self.assertTrue(leave.has_confirmed_order)

        with self.assertRaises(UserError):
            leave.action_refuse()
        with self.assertRaises(UserError):
            leave.action_back_to_approval()

    def test_draft_order_does_not_block_the_leave(self):
        """Only a CONFIRMED order locks the leave: a draft one leaves refusing
        available."""
        leave = self._make_leave(date(2028, 10, 1), date(2028, 10, 5))
        self._create_order_via_button(leave)
        leave.invalidate_recordset(['has_confirmed_order'])
        self.assertFalse(leave.has_confirmed_order)

        leave.action_refuse()
        self.assertEqual(leave.state, 'refuse')

    def _user_with(self, groups, login):
        # Odoo 19 renamed res.users.groups_id -> group_ids.
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'group_ids': [(6, 0, [self.env.ref(g).id for g in groups])],
        })

    def test_vacation_confirm_requires_hr_officer(self):
        """Issuing a vacation order needs Ukraine HR Officer rights — a plain
        HR user cannot confirm one."""
        from odoo.exceptions import UserError
        order = self._make_vacation_order(date(2028, 3, 1), date(2028, 3, 5))
        clerk = self._user_with(['base.group_user', 'hr.group_hr_user'],
                                'plain_hr_user')
        with self.assertRaises(UserError):
            order.with_user(clerk).action_confirm()
        self.assertEqual(order.state, 'draft')

    def test_vacation_confirm_by_officer_is_audited(self):
        """An HR officer may confirm; the order records who confirmed it and
        when."""
        order = self.env['hr.order'].create({
            'order_type': 'vacation',
            'employee_id': self.employee.id,
            'work_entry_type_id': self.leave_type.id,
            'vacation_date_from': date(2028, 4, 1),
            'vacation_date_to': date(2028, 4, 5),
            'date': date(2028, 4, 1),
            'subject': 'Vacation',
        })
        officer = self._user_with(
            ['base.group_user', 'l10n_ua_hr_base.group_hr_ua_officer'],
            'ua_hr_officer')

        order.with_user(officer).action_confirm()

        self.assertEqual(order.state, 'confirmed')
        self.assertEqual(order.confirmed_by_id, officer)
        self.assertTrue(order.confirmed_date)

    def test_officer_may_read_company_leaves(self):
        """The Ukraine HR Officer record rule lets an officer read another
        employee's time off in their company — core alone would hide it, and
        the order flow depends on that access."""
        from odoo.exceptions import AccessError
        leave = self._make_leave(date(2028, 6, 1), date(2028, 6, 5))
        officer = self._user_with(
            ['base.group_user', 'l10n_ua_hr_base.group_hr_ua_officer'],
            'ua_hr_officer_read')
        # The leave belongs to another employee, so a plain user cannot see it.
        plain = self._user_with(['base.group_user'], 'plain_employee_read')
        with self.assertRaises(AccessError):
            leave.with_user(plain).read(['state'])
        # The officer can.
        self.assertTrue(leave.with_user(officer).read(['state']))

    def test_refuse_leaves_a_draft_order_alone(self):
        """Refusing a leave neither deletes its draft order nor changes its
        state — orders move only through their own buttons."""
        leave = self._make_leave(date(2027, 12, 1), date(2027, 12, 5))
        order = self._create_order_via_button(leave)
        self.assertEqual(order.state, 'draft')

        leave.action_refuse()

        self.assertTrue(order.exists(), "The order must not be deleted.")
        self.assertEqual(order.state, 'draft',
                         "Refusing the leave must not change the order state.")
        self.assertEqual(leave.order_id, order, "The link must survive.")

    def test_cascade_delete(self):
        """Unlinking a draft leave also unlinks its draft order."""
        leave = self._make_leave(date(2027, 11, 1), date(2027, 11, 5))
        order = self._create_order_via_button(leave)
        self.assertTrue(order.exists())

        leave.unlink()

        self.assertFalse(order.exists(),
                         "The draft order was not cascade deleted with the leave.")
