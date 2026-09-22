from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
from odoo.addons.hr_holidays.models.hr_leave import HOURS_PER_DAY
from datetime import datetime, time as dt_time


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    calendar_days = fields.Integer(
        string='Calendar Days',
        compute='_compute_calendar_days',
        store=True
    )
    working_days = fields.Integer(
        string='Working Days',
        compute='_compute_working_days',
        store=True
    )

    average_daily_salary = fields.Float(
        string='Average Daily Salary',
        digits=(16, 2)
    )
    vacation_pay_amount = fields.Float(
        string='Vacation Pay Amount',
        compute='_compute_vacation_pay',
        store=True,
        digits=(16, 2)
    )

    order_number = fields.Char(string='Order Number')
    order_date = fields.Date(string='Order Date')

    order_id = fields.Many2one(
        'hr.order',
        string='Leave Order',
        ondelete='set null',
        copy=False,
        index=True,
        domain=[('order_type', '=', 'vacation')],
    )

    sick_leave_id = fields.Many2one(
        'hr.sick.leave',
        string='Sick Leave',
        ondelete='set null',
        copy=False,
        index=True,
        help='The sick leave certificate this absence records. Set when the '
             'absence is created from the certificate\'s "New Time Off" '
             'button.'
    )

    order_count = fields.Integer(
        string='Orders',
        compute='_compute_order_count',
        help='Number of vacation orders issued for THIS leave (0 or 1 — the '
             'leave and its order reference each other). Drives the "Orders" '
             'smart button.'
    )
    can_create_order = fields.Boolean(
        string='Can Create Order',
        compute='_compute_can_create_order',
        help='Technical: true when the "New Order" button should be shown — '
             'this leave has an employee and no order linked yet.'
    )

    @api.depends('order_id')
    def _compute_order_count(self):
        for leave in self:
            leave.order_count = len(leave._linked_orders())

    def _linked_orders(self):
        """Orders tied to THIS leave — not the employee's whole order history.

        Normally exactly the leave's own order_id; the reverse link
        (hr.order.leave_id) is unioned in as well so an order that points here
        without the back-link having been written yet is still surfaced."""
        self.ensure_one()
        orders = self.order_id
        origin_id = self._origin.id
        if origin_id:
            orders |= self.env['hr.order'].search(
                [('leave_id', '=', origin_id)])
        return orders

    has_confirmed_order = fields.Boolean(
        string='Covered by a Confirmed Order',
        compute='_compute_has_confirmed_order',
        help='Technical: true when a confirmed vacation order covers this '
             'leave. The order obliges the employee to take it, so the leave '
             'can no longer be refused or sent back to approval.'
    )

    @api.depends('order_id', 'order_id.state')
    def _compute_has_confirmed_order(self):
        for leave in self:
            leave.has_confirmed_order = (
                leave.order_id.state == 'confirmed' if leave.order_id
                else False)


    @api.depends('order_id', 'employee_id')
    def _compute_can_create_order(self):
        for leave in self:
            leave.can_create_order = bool(
                not leave.order_id and leave.employee_id)

    remaining_days_before = fields.Float(
        string='Balance Before',
        compute='_compute_remaining_before',
        store=True,
        help='Vacation balance before this leave'
    )
    remaining_days_after = fields.Float(
        string='Balance After',
        compute='_compute_remaining_after',
        store=True
    )

    vacation_year = fields.Integer(
        string='Vacation Year',
        help='Year of the leave start date. Computed automatically and '
        'read-only.',
        compute='_compute_vacation_year',
        store=True,
        readonly=True,
    )

    vacation_balance_id = fields.Many2one(
        'hr.vacation.balance',
        string='Vacation Period',
        index=True,
        domain="[('employee_id', '=', employee_id),"
               " ('leave_type_id', '=', work_entry_type_id)]",
        help='Accounting period this leave is charged against. Chosen manually '
             '(defaults to the period that contains today); the leave dates '
             'need not fall inside the selected period.'
    )

    @api.onchange('work_entry_type_id', 'employee_id', 'request_date_from')
    def _onchange_default_vacation_period(self):
        """When the leave type, employee or start date is set, backfill every
        accounting period for the employee/type from the hire date up to today
        (and up to the leave's first day when that day is later), then preselect
        the period the leave's FIRST DAY falls into — which may be a future
        period for a vacation planned ahead. HR can still change it to any
        period in the list; the leave dates need not fall inside the chosen
        period."""
        lt = self.work_entry_type_id
        emp = self.employee_id
        if not lt or not lt.ua_leave_category or not emp:
            return
        today = fields.Date.context_today(self)
        start = self.request_date_from or today
        self.vacation_balance_id = self.env['hr.vacation.balance'].sudo(
        )._ensure_periods_up_to(emp, lt, max(today, start), select_date=start)

    carryover_warning = fields.Char(
        string='Carry-over Warning',
        compute='_compute_carryover_warning',
        help='Non-blocking notice shown when unused days from the previous '
             'period cannot be fully carried over under this leave type\'s '
             'transfer rules (Transferable / Max Transfer Days).'
    )

    @api.depends('work_entry_type_id', 'request_date_from', 'employee_id',
                 'vacation_balance_id')
    def _compute_carryover_warning(self):
        for leave in self:
            leave.carryover_warning = leave._carryover_warning_message()

    def _carryover_warning_message(self):
        """Return a human-readable warning when the previous period leaves
        unused days that this leave type's transfer rules cannot carry over
        (they would be forfeited), or False when nothing is at risk. Purely
        advisory — never blocks saving."""
        self.ensure_one()
        lt = self.work_entry_type_id
        emp = self.employee_id
        if not lt or not emp or not self.request_date_from:
            return False
        Balance = self.env['hr.vacation.balance']
        _start, _end, index = self._resolve_leave_period()
        if not index:
            return False
        prev = Balance.search([
            ('employee_id', '=', emp.id),
            ('leave_type_id', '=', lt.id),
            ('period_index', '<', index),
        ], order='period_index desc', limit=1)
        if not prev or prev.remaining_days <= 0:
            return False
        allowed = Balance._allowed_carryover(lt, prev.remaining_days)
        lost = prev.remaining_days - allowed
        if lost <= 0:
            return False
        if not lt.is_transferable:
            return _(
                'Leave type "%(type)s" does not allow carrying days over: '
                '%(lost).1f unused day(s) from the previous period '
                '(%(period)s) will be forfeited.',
                type=lt.name, lost=lost, period=prev.period_label)
        return _(
            'Only %(max)s day(s) may be carried over for "%(type)s": '
            '%(lost).1f day(s) from the previous period (%(period)s) '
            'exceed the limit and will be forfeited.',
            max=lt.max_transfer_days, type=lt.name, lost=lost,
            period=prev.period_label)

    period_mismatch_warning = fields.Char(
        string='Vacation Period Notice',
        compute='_compute_period_mismatch_warning',
        help='Non-blocking notice shown when the leave starts outside the '
             'accounting period it is charged to. Recording a past period '
             'with current dates is allowed; the notice guards against '
             'picking the wrong period by mistake.'
    )

    @api.depends('vacation_balance_id', 'request_date_from')
    def _compute_period_mismatch_warning(self):
        for leave in self:
            leave.period_mismatch_warning = leave._period_mismatch_message()

    def _period_mismatch_message(self):
        """Return a human-readable notice when the leave's start date falls
        outside the accounting period it is charged to, or False when the two
        agree. Purely advisory: charging a leave to a period its dates do not
        cover is legitimate (e.g. taking last period's days now), so this never
        blocks saving — it only guards against picking the wrong period by
        mistake, which would silently distort that period's balance."""
        self.ensure_one()
        balance = self.vacation_balance_id
        start = self.request_date_from
        if not balance or not start:
            return False
        if not balance.period_start or not balance.period_end:
            return False
        if balance.period_start <= start <= balance.period_end:
            return False
        return _(
            'This leave starts on %(date)s, outside the selected vacation '
            'period "%(period)s" (%(start)s – %(end)s). This is allowed, but '
            'check that the period is the one you intended — the days are '
            'charged to it.',
            date=start.strftime('%d.%m.%Y'),
            period=balance.period_label or '',
            start=balance.period_start.strftime('%d.%m.%Y'),
            end=balance.period_end.strftime('%d.%m.%Y'),
        )

    @api.onchange('work_entry_type_id', 'request_date_from', 'request_date_to',
                  'employee_id', 'vacation_balance_id')
    def _onchange_vacation_warnings(self):
        """Pop a non-blocking warning on the form as soon as the chosen type,
        dates or accounting period need the user's attention: carried-over days
        that would be forfeited, and a period that does not cover the leave
        dates. Both are advisory — neither blocks saving."""
        messages = [m for m in (self._carryover_warning_message(),
                                self._period_mismatch_message()) if m]
        if messages:
            return {'warning': {
                'title': _('Vacation notice'),
                'message': '\n\n'.join(messages),
            }}

    def _compute_display_name(self):
        # Base hr_holidays builds the label as "<person> on <type>: ...".
        # The English " on " separator is left untranslated in the UA UI, so
        # swap it for " - " (first occurrence only — that is the separator).
        super()._compute_display_name()
        for leave in self:
            if leave.display_name and ' on ' in leave.display_name:
                leave.display_name = leave.display_name.replace(' on ', ' - ', 1)

    @api.depends('request_date_from')
    def _compute_vacation_year(self):
        # The vacation year always follows the leave's start date.
        for leave in self:
            leave.vacation_year = (
                leave.request_date_from.year if leave.request_date_from else 0)

    show_create_vacation_period = fields.Boolean(
        string='Can Create Vacation Period',
        compute='_compute_show_create_vacation_period',
        help='Technical: drives the "Create" button next to the Vacation '
             'Period field — true when the leave has no linked period yet '
             'but one can be resolved for its type and year.'
    )

    @api.depends('employee_id', 'work_entry_type_id',
                 'request_date_from', 'vacation_balance_id')
    def _compute_show_create_vacation_period(self):
        # Offered for any leave type available to the employee, as long as
        # the accounting period can be resolved (a hire anchor is needed
        # for work-year types; calendar types always resolve).
        for leave in self:
            show = False
            if (not leave.vacation_balance_id and leave.employee_id
                    and leave.work_entry_type_id):
                start, _end, _index = leave._resolve_leave_period()
                show = bool(start)
            leave.show_create_vacation_period = show

    def _resolve_leave_period(self):
        """Return (period_start, period_end, period_index) of the accounting
        period this leave belongs to — the one containing its start date.
        Works for both calendar and work years and keeps this method in step
        with _compute_vacation_balance. Returns (False, False, 0) when it
        cannot be resolved (e.g. a work-year type without a hire anchor)."""
        self.ensure_one()
        Balance = self.env['hr.vacation.balance']
        lt = self.work_entry_type_id
        emp = self.employee_id
        if not lt or not emp or not self.request_date_from:
            return (False, False, 0)
        return Balance._get_period_for(emp, lt, self.request_date_from)

    def action_create_vacation_period(self):
        """Create (or reuse) the hr.vacation.balance for this leave's
        resolved period and link it. Periods are normally created
        automatically on save; this stays as an explicit fallback."""
        self.ensure_one()
        balance = self.env['hr.vacation.balance'].sudo()._get_or_create_period(
            self.employee_id, self.work_entry_type_id, self.request_date_from)
        if not balance:
            raise UserError(_(
                'Cannot determine the accounting period. For work-year leave '
                'types, set the employee\'s hire date first.'))
        self.vacation_balance_id = balance.id
        return True

    @api.constrains('vacation_balance_id', 'request_date_from',
                    'work_entry_type_id', 'employee_id')
    def _check_vacation_balance_period(self):
        """Block saving only when the linked vacation period does not belong to
        the leave's employee and leave type. The period is chosen manually and
        the leave dates need NOT fall inside it (HR may record a past-period
        leave with current dates), so there is no date-containment check."""
        for leave in self:
            bal = leave.vacation_balance_id
            if not bal:
                continue
            if (bal.employee_id != leave.employee_id
                    or bal.leave_type_id != leave.work_entry_type_id):
                raise ValidationError(_(
                    'The vacation period does not belong to this employee '
                    'and leave type.'))

    @api.constrains('request_date_from', 'employee_id', 'work_entry_type_id')
    def _check_leave_after_hire(self):
        """A UA-managed leave cannot start before the employee was hired —
        neither the leave nor its accounting period may predate the hire
        date."""
        Balance = self.env['hr.vacation.balance']
        for leave in self:
            lt = leave.work_entry_type_id
            if (not lt or not lt.ua_leave_category
                    or not leave.employee_id or not leave.request_date_from):
                continue
            hire = Balance._employee_hire_anchor(leave.employee_id)
            if hire and leave.request_date_from < hire:
                raise ValidationError(_(
                    'Cannot record a "%(type)s" leave starting %(date)s for '
                    '%(employee)s, before the hire date (%(hire)s).',
                    type=lt.name,
                    date=leave.request_date_from.strftime('%d.%m.%Y'),
                    employee=leave.employee_id.name,
                    hire=hire.strftime('%d.%m.%Y'),
                ))

    def action_create_order(self):
        """Manual "Create Order" button. Opens a new vacation order form with
        every field pre-filled from the leave, so the user can review it and
        save it explicitly — the standard Odoo document-creation flow (no
        silent background creation). Saving links the order to this leave via
        default_leave_id, so no duplicate leave is spawned. Guarded so it never
        starts a second order."""
        self.ensure_one()
        if self.order_id:
            raise UserError(_('This leave already has a linked order.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Vacation Order'),
            'res_model': 'hr.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_order_type': 'vacation',
                'default_employee_id': self.employee_id.id,
                'default_department_id': self.employee_id.department_id.id,
                'default_job_id': self.employee_id.job_id.id,
                'default_leave_id': self.id,
                'default_vacation_date_from': self.request_date_from,
                'default_vacation_date_to': self.request_date_to,
                'default_subject': 'Про надання відпустки',
            },
        }

    def action_view_orders(self):
        """Smart button: open the order(s) issued for THIS leave — opening the
        form directly when there is just one, which is the normal case."""
        self.ensure_one()
        orders = self._linked_orders()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Vacation Orders'),
            'res_model': 'hr.order',
            'context': {'default_order_type': 'vacation',
                        'default_employee_id': self.employee_id.id,
                        'default_leave_id': self.id},
        }
        if len(orders) == 1:
            action.update({'view_mode': 'form', 'res_id': orders.id})
        else:
            action.update({'view_mode': 'list,form',
                           'domain': [('id', 'in', orders.ids)]})
        return action

    @api.model
    def default_get(self, fields_list):
        """Pre-fill the leave type on the new-leave form with the company's
        default type, so it shows up before the record is saved.
        hr_holidays' own default_get picks an arbitrary first type; we
        override it with res.company.l10n_ua_default_leave_type_id unless
        the caller passed an explicit default_work_entry_type_id via
        context."""
        res = super().default_get(fields_list)
        if ('work_entry_type_id' in fields_list
                and not self.env.context.get('default_work_entry_type_id')):
            company = self.env['res.company'].browse(
                res.get('company_id')) or self.env.company
            if company.l10n_ua_default_leave_type_id:
                res['work_entry_type_id'] = \
                    company.l10n_ua_default_leave_type_id.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # Preselect default leave type if not provided
        for vals in vals_list:
            if not vals.get('work_entry_type_id'):
                company = self.env['res.company'].browse(
                    vals.get('company_id')) or self.env.company
                if company.l10n_ua_default_leave_type_id:
                    vals['work_entry_type_id'] = \
                        company.l10n_ua_default_leave_type_id.id
        # A leave opened from an order's "New Time Off" button carries the
        # order in the context. Re-apply it here as well: navigating away from
        # the unsaved form and back can drop the field, which would silently
        # save an unlinked leave and let the order offer to create a second one.
        order_from_ctx = self.env.context.get('default_order_id')
        if order_from_ctx:
            for vals in vals_list:
                vals.setdefault('order_id', order_from_ctx)

        # Default the accounting period to the one the leave's FIRST DAY falls
        # into (backfilling every period for the type up to today, and up to
        # that day when it is later), UNLESS the caller set it explicitly (leave
        # form onchange, or a vacation order passing the period the user chose).
        # The period stays a manual choice; the leave dates need not fall inside
        # it, and a vacation planned ahead defaults to its future period.
        Balance = self.env['hr.vacation.balance']
        today = fields.Date.context_today(self)
        for vals in vals_list:
            emp_id = vals.get('employee_id')
            lt_id = vals.get('work_entry_type_id')
            if emp_id and lt_id and not vals.get('vacation_balance_id'):
                start = (fields.Date.to_date(vals.get('request_date_from'))
                         or fields.Date.to_date(vals.get('date_from'))
                         or today)
                period = Balance._ensure_periods_up_to(
                    self.env['hr.employee'].browse(emp_id),
                    self.env['hr.work.entry.type'].browse(lt_id),
                    max(today, start), select_date=start,
                )
                if period:
                    vals['vacation_balance_id'] = period.id

        # No order is auto-created on save: one is issued only through the
        # "New Order" button, which opens a pre-filled order form.
        leaves = super().create(vals_list)

        # A leave opened from an order's "New Time Off" button arrives with
        # order_id already set; complete the pair so the order points back.
        for leave in leaves:
            if leave.order_id and not leave.order_id.leave_id:
                leave.order_id.with_context(
                    _sync_order_leave=True, leave_skip_state_check=True
                ).write({'leave_id': leave.id})
            # Same for a leave opened from a sick leave's "New Time Off".
            if leave.sick_leave_id and not leave.sick_leave_id.leave_id:
                leave.sick_leave_id.write({'leave_id': leave.id})

        # Per-leave Balance Before/After for subsequent leaves in same year.
        leaves._recompute_subsequent_leaves()
        # Rollup fields used_days / planned_days on hr.vacation.balance.
        leaves._recompute_balances_for_keys(leaves._balance_keys())
        return leaves

    def _ensure_vacation_period(self):
        """Fill an empty accounting period with the one the leave's FIRST DAY
        falls into (backfilling periods up to today, or up to that day when it
        is later). Only leaves with no period yet are touched — a manually
        chosen period is never overwritten."""
        Balance = self.env['hr.vacation.balance']
        today = fields.Date.context_today(self)
        for leave in self:
            if (leave.vacation_balance_id
                    or not leave.employee_id or not leave.work_entry_type_id):
                continue
            start = leave.request_date_from or today
            period = Balance._ensure_periods_up_to(
                leave.employee_id, leave.work_entry_type_id,
                max(today, start), select_date=start)
            if period:
                leave.vacation_balance_id = period.id

    def write(self, vals):
        # Capture balance keys BEFORE the write so we also refresh rows
        # we move away from (e.g. employee_id or vacation_year changed).
        old_balance_keys = (
            self._balance_keys()
            if self._BALANCE_TRIGGER_FIELDS & vals.keys()
            else set()
        )
        result = super().write(vals)
        # After the dates are written (so request_date_from is up to date),
        # make sure each leave has its accounting period, creating it when
        # none exists yet. The stored compute already re-links to an existing
        # period; this only fills the gap. Skipped when the caller sets the
        # period explicitly in the same write.
        if ({'request_date_from', 'request_date_to', 'date_from', 'date_to',
             'employee_id', 'work_entry_type_id'} & vals.keys()
                and 'vacation_balance_id' not in vals):
            self._ensure_vacation_period()
        # Keep an already-linked order's dates in step with the leave, so edits
        # to the leave flow through to its draft order. Only dates travel —
        # states never do.
        if (not self.env.context.get('_sync_order_leave')
                and {'date_from', 'date_to', 'request_date_from',
                     'request_date_to'} & vals.keys()):
            for leave in self.filtered(lambda l: l.order_id):
                leave.order_id.with_context(_sync_order_leave=True).write({
                    'vacation_date_from': leave.request_date_from,
                    'vacation_date_to': leave.request_date_to,
                })
        # Per-leave Balance Before/After for subsequent leaves.
        if any(f in vals for f in ('date_from', 'date_to', 'request_date_from',
                                    'request_date_to', 'state', 'work_entry_type_id')):
            self._recompute_subsequent_leaves()
        # Rollup fields on hr.vacation.balance.
        if self._BALANCE_TRIGGER_FIELDS & vals.keys():
            self._recompute_balances_for_keys(old_balance_keys | self._balance_keys())
        return result

    def _action_validate(self, *args, **kwargs):
        # Approval is the moment a leave starts counting as USED, so make sure
        # it carries its accounting period. Leaves normally get one on create
        # or on a date/type change; this closes the remaining gaps (import, a
        # write that cleared the field, a period that could not be resolved
        # earlier). Done before the state flips, while the record is still
        # freely writable. Leaves that still cannot resolve a period are left
        # untouched — the balance's date-based fallback picks them up.
        self._ensure_vacation_period()
        # Nothing is done to the order from here: orders are created and
        # confirmed only through their own buttons. Approving a leave whose
        # order is already confirmed stays allowed on purpose — the order may
        # have been issued first and the leave confirmed afterwards.
        return super()._action_validate(*args, **kwargs)

    def _check_order_allows_cancelling(self, action):
        """Block undoing a leave that a confirmed order already covers.

        The order is the legal document that obliges the employee to take the
        leave, so once it is confirmed the leave cannot be refused or sent back
        to approval — the order would have to be cancelled first."""
        blocked = self.filtered(
            lambda l: l.order_id and l.order_id.state == 'confirmed')
        if blocked:
            raise UserError(_(
                'Leave of %(employee)s is covered by confirmed vacation order '
                '%(order)s, so it cannot be %(action)s. Cancel the order '
                'first.',
                employee=blocked[0].employee_id.name,
                order=blocked[0].order_id.name or '',
                action=action))

    def action_refuse(self, *args, **kwargs):
        self._check_order_allows_cancelling(_('refused'))
        return super().action_refuse(*args, **kwargs)

    def action_back_to_approval(self, *args, **kwargs):
        self._check_order_allows_cancelling(_('sent back to approval'))
        return super().action_back_to_approval(*args, **kwargs)

    def unlink(self):
        # Capture balance keys before deletion so we can refresh the
        # rollup rows those leaves used to contribute to.
        affected_balance_keys = self._balance_keys()
        # Capture subsequent leaves before deletion so we can refresh
        # their per-leave Balance Before/After after super().unlink().
        leaves_to_recompute = self.env['hr.leave']
        for leave in self:
            if leave.employee_id and leave.work_entry_type_id and leave.request_date_from:
                period_domain = leave._period_domain()
                if period_domain is None:
                    continue
                leaves_to_recompute |= self.env['hr.leave'].search([
                    ('employee_id', '=', leave.employee_id.id),
                    ('work_entry_type_id', '=', leave.work_entry_type_id.id),
                    ('request_date_from', '>', leave.request_date_from),
                    *period_domain,
                    ('id', 'not in', self.ids)
                ])
        orders_to_delete = self.filtered(
            lambda l: l.order_id
            and l.state != 'validate'
            and l.order_id.state == 'draft'
        ).mapped('order_id')
        res = super().unlink()
        if orders_to_delete:
            orders_to_delete.with_context(_sync_order_leave=True).unlink()
        if leaves_to_recompute:
            leaves_to_recompute._compute_remaining_before()
            leaves_to_recompute._compute_remaining_after()
        self._recompute_balances_for_keys(affected_balance_keys)
        return res

    @api.constrains('employee_id', 'work_entry_type_id', 'date_from')
    def _check_minimum_experience(self):
        """Check minimum work experience for first annual leave.

        Per Ukrainian law, employee must work 6 months before first annual leave.
        Exception: pregnant women, minors, part-time workers, etc.
        """
        for leave in self:
            if not leave.work_entry_type_id or not leave.work_entry_type_id.requires_experience:
                continue
            if not leave.employee_id or not leave.date_from:
                continue

            min_months = leave.work_entry_type_id.min_experience_months or 6

            # Get contract start date from version (Odoo 19)
            version = leave.employee_id.current_version_id
            if not version or not version.contract_date_start:
                continue

            contract_start = version.contract_date_start
            experience_date = contract_start + relativedelta(months=min_months)
            if leave.date_from.date() < experience_date:
                existing_leaves = self.env['hr.leave'].search_count([
                    ('employee_id', '=', leave.employee_id.id),
                    ('work_entry_type_id', '=', leave.work_entry_type_id.id),
                    ('state', '=', 'validate'),
                    ('id', '!=', leave.id),
                ])
                if existing_leaves == 0:
                    raise ValidationError(_(
                        'Employee %(employee)s must work at least %(months)s months before first annual leave. '
                        'Current experience: %(current)s months.',
                        employee=leave.employee_id.name,
                        months=min_months,
                        current=(leave.date_from.date() - contract_start).days // 30,
                    ))

    @api.onchange('employee_id', 'date_from', 'work_entry_type_id')
    def _onchange_calculate_vacation_pay(self):
        """Auto-calculate average salary when creating vacation"""
        if self.employee_id and self.date_from and self.work_entry_type_id:
            if self.work_entry_type_id.is_paid:
                self.average_daily_salary = self._calculate_average_salary()

    @api.depends('request_date_from', 'request_date_to')
    def _compute_calendar_days(self):
        for leave in self:
            if leave.request_date_from and leave.request_date_to:
                delta = leave.request_date_to - leave.request_date_from
                total_days = delta.days + 1
                public_holidays = leave._get_public_holidays_count()
                leave.calendar_days = max(total_days - public_holidays, 0)
            else:
                leave.calendar_days = 0

    @api.depends('date_from', 'date_to', 'resource_calendar_id', 'work_entry_type_id.request_unit',
                 'work_entry_type_id.is_calendar_days', 'request_date_from', 'request_date_to')
    def _compute_duration(self):
        calendar_days_leaves = self.filtered(
            lambda l: l.work_entry_type_id and l.work_entry_type_id.is_calendar_days
        )
        other_leaves = self - calendar_days_leaves

        for leave in calendar_days_leaves:
            if leave.request_date_from and leave.request_date_to:
                delta = leave.request_date_to - leave.request_date_from
                total_days = delta.days + 1
                public_holidays = leave._get_public_holidays_count()
                days = max(total_days - public_holidays, 0)
                leave.number_of_days = days
                hours_per_day = leave.resource_calendar_id.hours_per_day or HOURS_PER_DAY
                leave.number_of_hours = days * hours_per_day
            else:
                leave.number_of_days = 0
                leave.number_of_hours = 0

        if other_leaves:
            super(HrLeave, other_leaves)._compute_duration()

    def _get_public_holidays_count(self):
        self.ensure_one()
        if not self.request_date_from or not self.request_date_to:
            return 0
        leave_from = self.request_date_from
        leave_to = self.request_date_to
        dt_from = datetime.combine(leave_from, dt_time.min)
        dt_to = datetime.combine(leave_to, dt_time.max)
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', dt_to),
            ('date_to', '>=', dt_from),
        ])
        count = 0
        for holiday in public_holidays:
            h_from = max(holiday.date_from.date(), leave_from)
            h_to = min(holiday.date_to.date(), leave_to)
            if h_from <= h_to:
                count += (h_to - h_from).days + 1
        return count

    @api.depends('request_date_from', 'request_date_to')
    def _compute_working_days(self):
        for leave in self:
            if leave.request_date_from and leave.request_date_to:
                leave_from = leave.request_date_from
                leave_to = leave.request_date_to
                dt_from = datetime.combine(leave_from, dt_time.min)
                dt_to = datetime.combine(leave_to, dt_time.max)
                public_holidays = self.env['resource.calendar.leaves'].search([
                    ('resource_id', '=', False),
                    ('date_from', '<=', dt_to),
                    ('date_to', '>=', dt_from),
                ])
                holiday_dates = set()
                for h in public_holidays:
                    d = max(h.date_from.date(), leave_from)
                    end_h = min(h.date_to.date(), leave_to)
                    while d <= end_h:
                        holiday_dates.add(d)
                        d += relativedelta(days=1)
                count = 0
                current = leave_from
                while current <= leave_to:
                    if current.weekday() < 5 and current not in holiday_dates:
                        count += 1
                    current += relativedelta(days=1)
                leave.working_days = count
            else:
                leave.working_days = 0

    @api.depends('calendar_days', 'average_daily_salary', 'work_entry_type_id.is_paid')
    def _compute_vacation_pay(self):
        for leave in self:
            if leave.work_entry_type_id.is_paid and leave.average_daily_salary:
                leave.vacation_pay_amount = leave.calendar_days * leave.average_daily_salary
            else:
                leave.vacation_pay_amount = 0.0

    @api.depends('employee_id', 'work_entry_type_id', 'vacation_balance_id',
                 'vacation_year', 'request_date_from')
    def _compute_remaining_before(self):
        """Computes the balance before the start of a specific leave in chronological order."""
        for leave in self:
            if not leave.employee_id or not leave.work_entry_type_id:
                leave.remaining_days_before = 0
                continue

            balance = leave.vacation_balance_id
            if balance:
                # Linked accounting period is the single source of truth:
                # its bounds work for both calendar and work years.
                total_available = balance.total_available
                period_start = balance.period_start
                period_end = balance.period_end
                period_domain = [
                    '|', ('vacation_balance_id', '=', balance.id),
                         '&', ('vacation_balance_id', '=', False),
                              '&', ('request_date_from', '>=', period_start),
                                   ('request_date_from', '<=', period_end),
                ]
            else:
                # No balance row yet — legacy year-based fallback.
                year = leave.vacation_year or (
                    leave.request_date_from.year if leave.request_date_from else False
                )
                if not year:
                    leave.remaining_days_before = 0
                    continue
                total_available = leave.work_entry_type_id.annual_days or 0
                period_start = fields.Date.from_string(f'{year}-01-01')
                period_domain = [
                    '|', ('vacation_year', '=', year),
                         '&', ('request_date_from', '>=', f'{year}-01-01'),
                              ('request_date_from', '<=', f'{year}-12-31'),
                ]

            # Find leaves of the same period. Chronological mode
            # (request_date_from set on the leave): only earlier-starting
            # leaves. Period-aggregate fallback (no request_date_from yet —
            # e.g. a draft in the form): all period's leaves so the value
            # reflects "available − already used/planned this period".
            domain = [
                ('employee_id', '=', leave.employee_id.id),
                ('work_entry_type_id', '=', leave.work_entry_type_id.id),
                ('state', 'not in', ['cancel', 'refuse']), # Count both planned and approved leaves
            ] + period_domain
            # Apply the chronological "earlier than this leave" filter ONLY
            # when the leave's start date falls within (or after) the period
            # we are computing. For a brand-new draft, Odoo's hr.leave fills
            # request_date_from with today() by default — applying the
            # filter in that case would exclude future-period leaves and
            # break the aggregate fallback.
            if leave.request_date_from and leave.request_date_from >= period_start:
                domain.append(('request_date_from', '<', leave.request_date_from))

            # If this is an existing record (not a new one in the form), exclude it
            if leave._origin.id:
                domain.append(('id', '!=', leave._origin.id))

            previous_leaves = self.env['hr.leave'].search(domain)

            # Sum the CALENDAR days of previous leaves
            used_before = sum(previous_leaves.mapped('calendar_days'))

            leave.remaining_days_before = total_available - used_before

    @api.depends('remaining_days_before', 'calendar_days')
    def _compute_remaining_after(self):
        for leave in self:
            leave.remaining_days_after = (leave.remaining_days_before or 0) - (leave.calendar_days or 0)

    # =================================================================================
    # TRIGGERS FOR CHRONOLOGICAL RECOMPUTATION
    # =================================================================================

    # ------------------------------------------------------------------
    # Inverse trigger: keep hr.vacation.balance rollup fields in sync
    # with hr.leave. The stored used_days / planned_days fields on the
    # balance row cannot @api.depends on a cross-model search, so we
    # recompute affected balances explicitly whenever a leave is created,
    # modified or deleted. Runs alongside _recompute_subsequent_leaves
    # which keeps per-leave Balance Before/After in sync (different
    # concern, same hook points).
    # ------------------------------------------------------------------
    _BALANCE_TRIGGER_FIELDS = frozenset({
        'state', 'employee_id', 'work_entry_type_id',
        'date_from', 'date_to',
        'request_date_from', 'request_date_to',
        'vacation_year', 'vacation_balance_id',
    })

    def _period_domain(self):
        """Return the search domain matching leaves of the same accounting
        period as this leave: the linked balance's period when available,
        the legacy calendar year otherwise."""
        self.ensure_one()
        balance = self.vacation_balance_id
        if balance:
            return [
                '|', ('vacation_balance_id', '=', balance.id),
                     '&', ('vacation_balance_id', '=', False),
                          '&', ('request_date_from', '>=', balance.period_start),
                               ('request_date_from', '<=', balance.period_end),
            ]
        year = self.vacation_year or (
            self.request_date_from.year if self.request_date_from else False)
        if not year:
            return None
        return [
            '|', ('vacation_year', '=', year),
                 '&', ('request_date_from', '>=', f'{year}-01-01'),
                      ('request_date_from', '<=', f'{year}-12-31'),
        ]

    def _balance_keys(self):
        """Return ids of the hr.vacation.balance rows charged by leaves in self:
        the period each leave is explicitly linked to (used/planned days are
        counted by that link, not by the leave dates).

        A leave with NO period linked is charged, as a safety net, to the period
        its start date falls into (see
        hr.vacation.balance._charged_leaves_domain) — include that period too,
        so editing such a leave refreshes the rollups it feeds."""
        keys = set(self.mapped('vacation_balance_id').ids)
        unlinked = self.filtered(
            lambda l: not l.vacation_balance_id and l.employee_id
            and l.work_entry_type_id and l.request_date_from)
        if unlinked:
            Balance = self.env['hr.vacation.balance'].sudo()
            for leave in unlinked:
                fallback = Balance.search([
                    ('employee_id', '=', leave.employee_id.id),
                    ('leave_type_id', '=', leave.work_entry_type_id.id),
                    ('period_start', '<=', leave.request_date_from),
                    ('period_end', '>=', leave.request_date_from),
                ], limit=1)
                if fallback:
                    keys.add(fallback.id)
        return keys

    @api.model
    def _recompute_balances_for_keys(self, keys):
        if not keys:
            return
        balances = self.env['hr.vacation.balance'].sudo().browse(keys).exists()
        if balances:
            balances.invalidate_recordset([
                'used_days', 'planned_days',
                'total_available', 'remaining_days',
            ])
            balances._compute_used_days()
            balances._compute_totals()
            # A change in used days shifts remaining days, which the next
            # period carries over — propagate it forward.
            balances._recompute_carryover_chain()

    def _recompute_subsequent_leaves(self):
        """Helper method: forcibly updates the balance for leaves that come AFTER the current one."""
        for leave in self:
            if not leave.employee_id or not leave.work_entry_type_id or not leave.request_date_from:
                continue
            period_domain = leave._period_domain()
            if period_domain is None:
                continue

            # Find all leaves with a date greater than the date of the changed leave
            subsequent_leaves = self.env['hr.leave'].search([
                ('employee_id', '=', leave.employee_id.id),
                ('work_entry_type_id', '=', leave.work_entry_type_id.id),
                ('request_date_from', '>', leave.request_date_from),
                *period_domain,
                ('id', '!=', leave.id)
            ])
            if subsequent_leaves:
                # 1. recalculate leaves
                subsequent_leaves._compute_remaining_before()
                subsequent_leaves._compute_remaining_after()
                # 2. Store data to the database
                subsequent_leaves.flush_recordset(['remaining_days_before', 'remaining_days_after'])

    def action_calculate_vacation_pay(self):
        """Calculate average daily salary and vacation pay"""
        for leave in self:
            if not leave.employee_id or not leave.date_from:
                continue

            avg_salary = leave._calculate_average_salary()
            leave.average_daily_salary = avg_salary
        return True

    def _calculate_average_salary(self):
        """Calculate average daily salary for vacation pay.

        According to Resolution of CMU No. 100 from 08.02.1995:
        Formula: Total earnings / Calendar days in period

        Include:
        - Base salary
        - Bonuses marked as is_basic_salary
        - Allowances marked as is_basic_salary

        Exclude periods:
        - Sick leave
        - Unpaid leave
        - Idle time
        """
        self.ensure_one()

        date_to = self.date_from.date() - relativedelta(days=1)
        date_from = date_to - relativedelta(months=12) + relativedelta(days=1)

        # Get payslips for the period
        # Розрахунковий листок дає `l10n_ua_hr_salary`, якого цей модуль не
        # вимагає, — перевіряємо модель, а не поля на ній (див. hr_sick_leave).
        payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', '=', 'done'),
        ]) if 'hr.payslip' in self.env else None

        if not payslips:
            # Fallback to version wage (Odoo 19 uses version_ids instead of contract_id)
            version = self.employee_id.current_version_id
            if version and version.wage:
                # Оклад може бути у валюті — курс на початок відпустки.
                wage = version._l10n_ua_wage_in_company_currency(date_to)
                return round(wage / 29.3, 2)
            return 0.0

        # Calculate total earnings from payslip lines
        total_earnings = 0.0
        excluded_days = 0

        for payslip in payslips:
            # УВАГА: береться весь нарахований дохід — див. коментар-близнюк
            # у `hr_sick_leave.py`. Відбір за `is_basic_salary` тут не
            # застосовується й ніколи не застосовувався.
            total_earnings += payslip.gross_salary or 0

        # Calculate excluded days from sick leave and unpaid leave in the period
        sick_leave_type = self.env['hr.work.entry.type'].search([
            ('ua_leave_category', '=', 'sick')
        ], limit=1)
        unpaid_leave_type = self.env['hr.work.entry.type'].search([
            ('ua_leave_category', '=', 'unpaid')
        ])

        excluded_leave_types = sick_leave_type.ids + unpaid_leave_type.ids
        if excluded_leave_types:
            excluded_leaves = self.env['hr.leave'].search([
                ('employee_id', '=', self.employee_id.id),
                ('work_entry_type_id', 'in', excluded_leave_types),
                ('state', '=', 'validate'),
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
            ])
            excluded_days = sum(excluded_leaves.mapped('number_of_days'))

        # Count public holidays in the calculation period
        public_holidays = self.env['resource.calendar.leaves'].search_count([
            ('resource_id', '=', False),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
        ])

        # Calculate calendar days in period (excluding public holidays and excluded periods)
        # Formula per CMU Resolution No. 100: earnings / (calendar days - public holidays - excluded days)
        calendar_days = (date_to - date_from).days + 1 - public_holidays - excluded_days

        if calendar_days > 0:
            return round(total_earnings / calendar_days, 2)
        return 0.0
