from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrOrder(models.Model):
    """The vacation order's link to the time off it grants.

    hr.order lives in l10n_ua_hr_documents, which knows nothing of hr.leave:
    the reverse side of the link (hr.leave.order_id, calendar_days,
    vacation_balance_id) is defined here, and a module cannot depend on the
    one that depends on it. Both ends of the pair therefore live in this
    module, and l10n_ua_hr_documents installs on its own, without
    hr_holidays.
    """
    _inherit = 'hr.order'

    leave_id = fields.Many2one(
        'hr.leave',
        string='Leave Record',
        ondelete='set null',
        copy=False,
        index=True,
    )
    leave_count = fields.Integer(
        string='Time Off',
        compute='_compute_leave_count',
        help='Number of time off records tied to THIS order (0 or 1 — the '
             'order and its leave reference each other). Drives the "Time '
             'Off" smart button on vacation orders.'
    )

    can_create_leave = fields.Boolean(
        string='Can Create Time Off',
        compute='_compute_can_create_leave',
        help='Technical: true when the "New Time Off" button should be shown — '
             'a vacation order with all its details filled in and no time off '
             'linked yet.'
    )

    sick_leave_id = fields.Many2one(
        'hr.sick.leave',
        string='Sick Leave',
        ondelete='set null',
        copy=False,
        index=True,
        help='The sick leave certificate this order is issued for. Set when '
             'the order is created from the certificate\'s "New Order" button.'
    )

    # Related field — eliminates duplication
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Leave Type',
        related='leave_id.holiday_status_id',
        store=True,
        readonly=False,   # writable for orders being created standalone before leave is linked
        precompute=True,
        tracking=True,
    )

    @api.depends('leave_id')
    def _compute_is_locked(self):
        """A linked time off locks the data both documents must agree on.

        The base module has nothing to lock an order against and always
        reports False; the form binds its readonly attributes to this field so
        the link lives here alone.
        """
        for order in self:
            order.is_locked = bool(order.leave_id)

    @api.depends('order_type', 'leave_id', 'employee_id', 'holiday_status_id',
                 'vacation_date_from', 'vacation_date_to')
    def _compute_can_create_leave(self):
        for order in self:
            order.can_create_leave = bool(
                order.order_type == 'vacation' and not order.leave_id
                and order.employee_id and order.holiday_status_id
                and order.vacation_date_from and order.vacation_date_to)

    def action_create_leave(self):
        """"New Time Off" button. Opens a leave form pre-filled from this
        order so the user can review and save it — the same explicit flow the
        leave form uses to issue an order. Nothing is created until they save;
        default_order_id links the two sides back together."""
        self.ensure_one()
        if self.leave_id:
            raise UserError(_('This order already has a linked time off.'))
        if self.order_type != 'vacation':
            raise UserError(_('Only a vacation order records time off.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Time Off'),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_holiday_status_id': self.holiday_status_id.id,
                'default_request_date_from': self.vacation_date_from,
                'default_request_date_to': self.vacation_date_to,
                'default_order_id': self.id,
            },
        }

    @api.depends('leave_id')
    def _compute_leave_count(self):
        # Elevated: HR officers can read their companies' time off, but a
        # plain HR user may also open a vacation order, and for them the core
        # rule hides another employee's leave. A stat number on a smart button
        # must never make the form unopenable.
        for order in self:
            order.leave_count = len(order.sudo()._linked_leaves())

    def _linked_leaves(self):
        """Leaves tied to THIS order — not the employee's whole time off
        history. Normally exactly the order's own leave_id; the reverse link
        (hr.leave.order_id) is unioned in as well so a leave pointing here
        without the back-link having been written yet is still surfaced."""
        self.ensure_one()
        leaves = self.leave_id
        origin_id = self._origin.id
        if origin_id:
            leaves |= self.env['hr.leave'].search(
                [('order_id', '=', origin_id)])
        return leaves

    def action_view_leaves(self):
        """Smart button: open the time off record(s) tied to THIS order —
        opening the form directly when there is just one (the normal case)."""
        self.ensure_one()
        leaves = self._linked_leaves()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Time Off'),
            'res_model': 'hr.leave',
            'context': {'default_employee_id': self.employee_id.id},
        }
        if len(leaves) == 1:
            action.update({'view_mode': 'form', 'res_id': leaves.id})
        else:
            action.update({'view_mode': 'list,form',
                           'domain': [('id', 'in', leaves.ids)]})
        return action

    @api.model_create_multi
    def create(self, vals_list):
        # No time off is auto-created for a vacation order. It is created only
        # through the "New Time Off" button, which opens a leave form
        # pre-filled from the order for the user to review and save.

        # An order opened from a leave's "New Order" button carries the leave
        # in the context. Re-apply it: navigating away from the unsaved form
        # and back can drop the field, which would save an unlinked order and
        # let the leave offer to create a second one.
        leave_from_ctx = self.env.context.get('default_leave_id')
        if leave_from_ctx:
            for vals in vals_list:
                vals.setdefault('leave_id', leave_from_ctx)

        # An order opened from a sick leave's "New Order" button carries the
        # certificate in the context; re-apply it the same way, so navigating
        # away from the unsaved form and back cannot save an unlinked order.
        sick_leave_from_ctx = self.env.context.get('default_sick_leave_id')
        if sick_leave_from_ctx:
            for vals in vals_list:
                vals.setdefault('sick_leave_id', sick_leave_from_ctx)

        # Add _sync_order_leave context to prevent duplicate orders on inverse
        # related fields write. leave_skip_state_check lets the order write to
        # its own linked leave (e.g. the related holiday_status_id inverse)
        # without hr_holidays raising "modification not allowed in the current
        # state" when the leave is past draft/confirm.
        orders = super(HrOrder, self.with_context(
            _sync_order_leave=True, leave_skip_state_check=True)).create(vals_list)

        # Back-link leaves → orders in a single write per leave
        for order in orders:
            if order.leave_id and not order.leave_id.order_id:
                order.leave_id.with_context(
                    _sync_order_leave=True, leave_skip_state_check=True
                ).write({'order_id': order.id})
            if order.sick_leave_id and not order.sick_leave_id.order_id:
                order.sick_leave_id.write({'order_id': order.id})

        # Hand the records back in the caller's own environment. Both keys
        # above switch off a safeguard — the date sync of write() and the
        # leave's state check — and a recordset carries its context wherever
        # it goes, so returning `orders` as they are would leave a caller that
        # writes through them silently skipping both. The form never notices
        # (it re-reads the order on the next request); server-side code does.
        return orders.with_env(self.env)

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('_sync_order_leave'):
            if {'vacation_date_from', 'vacation_date_to'} & vals.keys():
                for order in self.filtered(
                    lambda o: o.order_type == 'vacation'
                    and o.leave_id
                    # Only push dates onto a still-editable leave; an approved,
                    # refused or cancelled leave must not be silently rewritten
                    # (and hr_holidays would block it anyway).
                    and o.leave_id.state in ('draft', 'confirm')
                ):
                    order.leave_id.with_context(
                        _sync_order_leave=True, leave_skip_state_check=True
                    ).write({
                        'date_from': fields.Datetime.from_string(str(order.vacation_date_from)) if order.vacation_date_from else False,
                        'date_to': fields.Datetime.from_string(str(order.vacation_date_to)) if order.vacation_date_to else False,
                    })
        return result

    def action_cancel(self):
        res = super().action_cancel()
        for order in self.filtered(lambda o: o.leave_id):
            order.leave_id.message_post(
                body=_('Linked vacation order %s was cancelled. Leave state is unchanged.', order.name)
            )
        return res

    def unlink(self):
        leaves = self.mapped('leave_id')
        res = super().unlink()
        for leave in leaves.exists():
            leave.message_post(body=_('Linked vacation order was deleted.'))
        return res

    @api.onchange('order_type')
    def _onchange_order_type_default_leave_type(self):
        """Preselect the company's default vacation type as soon as the order
        becomes a vacation order, the same default the leave form applies.
        An explicit choice is never overwritten."""
        if self.order_type != 'vacation' or self.holiday_status_id:
            return
        company = self.company_id or self.env.company
        default_lt = self.env['hr.leave.type'].search([
            ('ua_is_default', '=', True),
            ('company_id', '=', company.id),
        ], limit=1)
        if default_lt:
            self.holiday_status_id = default_lt
