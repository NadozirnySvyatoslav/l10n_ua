from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
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
        help='Year for which vacation is taken',
        compute='_compute_vacation_year',
        store=True,
        readonly=False,
        precompute=True,
    )

    @api.depends('request_date_from')
    def _compute_vacation_year(self):
        for leave in self:
            if leave.request_date_from:
                leave.vacation_year = leave.request_date_from.year

    @api.onchange('order_id')
    def _onchange_order_id(self):
        if self.order_id:
            self.order_number = self.order_id.name
            self.order_date = self.order_id.date

    def action_view_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.order',
            'res_id': self.order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        # Resolve which leaves should auto-create an order
        type_ids = {v.get('holiday_status_id') for v in vals_list if v.get('holiday_status_id')}
        types_with_order = set()
        if type_ids:
            types_with_order = set(self.env['hr.leave.type'].browse(type_ids).filtered(
                lambda t: t.create_order
            ).ids)

        order_vals_list = []
        order_indices = []
        for idx, vals in enumerate(vals_list):
            if (not vals.get('order_id')
                    and not self.env.context.get('_creating_leave_from_order')
                    and vals.get('holiday_status_id') in types_with_order):
                order_vals_list.append({
                    'order_type': 'vacation',
                    'employee_id': vals.get('employee_id'),
                    'vacation_date_from': fields.Date.to_date(vals.get('date_from')),
                    'vacation_date_to': fields.Date.to_date(vals.get('date_to')),
                    # holiday_status_id auto-derived from leave_id (related)
                })
                order_indices.append(idx)

        if order_vals_list:
            orders = self.env['hr.order'].with_context(
                _creating_order_from_leave=True
            ).create(order_vals_list)
            for idx, order in zip(order_indices, orders):
                vals_list[idx]['order_id'] = order.id
                vals_list[idx].setdefault('order_number', order.name)
                vals_list[idx].setdefault('order_date', order.date)

        leaves = super().create(vals_list)

        # Back-link orders → leaves + sync dates from already-computed leave
        for leave in leaves:
            if leave.order_id and not leave.order_id.leave_id:
                date_from = leave.date_from.date() if leave.date_from else leave.request_date_from
                date_to = leave.date_to.date() if leave.date_to else leave.request_date_to
                leave.order_id.with_context(_sync_order_leave=True).write({
                    'leave_id': leave.id,
                    'vacation_date_from': date_from,
                    'vacation_date_to': date_to,
                    'department_id': leave.employee_id.department_id.id,
                    'job_id': leave.employee_id.job_id.id,
                })
        # Per-leave Balance Before/After for subsequent leaves in same year.
        leaves._recompute_subsequent_leaves()
        # Rollup fields used_days / planned_days on hr.vacation.balance.
        leaves._recompute_balances_for_keys(leaves._balance_keys())               
        return leaves

    def write(self, vals):
        # Capture balance keys BEFORE the write so we also refresh rows
        # we move away from (e.g. employee_id or vacation_year changed).
        old_balance_keys = (
            self._balance_keys()
            if self._BALANCE_TRIGGER_FIELDS & vals.keys()
            else set()
        )        
        result = super().write(vals)
        # Add a check for _creating_leave_from_order to avoid order duplication
        if not self.env.context.get('_sync_order_leave') and not self.env.context.get('_creating_leave_from_order'):
            if {'date_from', 'date_to'} & vals.keys():
                for leave in self.filtered(lambda l: l.order_id):
                    leave.order_id.with_context(_sync_order_leave=True).write({
                        'vacation_date_from': leave.date_from.date() if leave.date_from else False,
                        'vacation_date_to': leave.date_to.date() if leave.date_to else False,
                    })
            if 'holiday_status_id' in vals:
                for leave in self.filtered(
                    lambda l: not l.order_id
                    and l.holiday_status_id
                    and l.holiday_status_id.create_order
                    and l.state not in ('validate', 'validate1', 'refuse')
                ):
                    order = self.env['hr.order'].with_context(
                        _creating_order_from_leave=True
                    ).create({
                        'order_type': 'vacation',
                        'employee_id': leave.employee_id.id,
                        'department_id': leave.employee_id.department_id.id,
                        'job_id': leave.employee_id.job_id.id,
                        'vacation_date_from': leave.date_from.date() if leave.date_from else False,
                        'vacation_date_to': leave.date_to.date() if leave.date_to else False,
                        'subject': 'Про надання відпустки',
                    })
                    leave.with_context(_sync_order_leave=True).write({'order_id': order.id})
                    order.with_context(_sync_order_leave=True).write({'leave_id': leave.id})
        # Per-leave Balance Before/After for subsequent leaves.
        if any(f in vals for f in ('date_from', 'date_to', 'request_date_from',
                                    'request_date_to', 'state', 'holiday_status_id')):
            self._recompute_subsequent_leaves()
        # Rollup fields on hr.vacation.balance.
        if self._BALANCE_TRIGGER_FIELDS & vals.keys():
            self._recompute_balances_for_keys(old_balance_keys | self._balance_keys())                   
        return result

    def _action_validate(self, *args, **kwargs):
        res = super()._action_validate(*args, **kwargs)
        for leave in self.filtered(lambda l: l.order_id and l.order_id.state == 'draft'):
            leave.order_id.with_context(_sync_order_leave=True).action_confirm()
        return res

    def action_refuse(self, *args, **kwargs):
        res = super().action_refuse(*args, **kwargs)
        for leave in self.filtered(lambda l: l.order_id and l.order_id.state != 'cancelled'):
            leave.order_id.with_context(_sync_order_leave=True).write({'state': 'cancelled'})
        return res

    def unlink(self):
        # Capture balance keys before deletion so we can refresh the
        # rollup rows those leaves used to contribute to.
        affected_balance_keys = self._balance_keys()
        # Capture subsequent leaves before deletion so we can refresh
        # their per-leave Balance Before/After after super().unlink().
        leaves_to_recompute = self.env['hr.leave']
        for leave in self:
            if leave.employee_id and leave.holiday_status_id and leave.request_date_from:
                year = leave.vacation_year or leave.request_date_from.year
                leaves_to_recompute |= self.env['hr.leave'].search([
                    ('employee_id', '=', leave.employee_id.id),
                    ('holiday_status_id', '=', leave.holiday_status_id.id),
                    ('request_date_from', '>', leave.request_date_from),
                    '|', ('vacation_year', '=', year),
                         '&', ('request_date_from', '>=', f'{year}-01-01'),
                              ('request_date_from', '<=', f'{year}-12-31'),
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

    @api.constrains('employee_id', 'holiday_status_id', 'date_from')
    def _check_minimum_experience(self):
        """Check minimum work experience for first annual leave.

        Per Ukrainian law, employee must work 6 months before first annual leave.
        Exception: pregnant women, minors, part-time workers, etc.
        """
        for leave in self:
            if not leave.holiday_status_id or not leave.holiday_status_id.requires_experience:
                continue
            if not leave.employee_id or not leave.date_from:
                continue

            min_months = leave.holiday_status_id.min_experience_months or 6

            # Get contract start date from version (Odoo 19)
            version = leave.employee_id.current_version_id
            if not version or not version.contract_date_start:
                continue

            contract_start = version.contract_date_start
            experience_date = contract_start + relativedelta(months=min_months)
            if leave.date_from.date() < experience_date:
                existing_leaves = self.env['hr.leave'].search_count([
                    ('employee_id', '=', leave.employee_id.id),
                    ('holiday_status_id', '=', leave.holiday_status_id.id),
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

    @api.onchange('employee_id', 'date_from', 'holiday_status_id')
    def _onchange_calculate_vacation_pay(self):
        """Auto-calculate average salary when creating vacation"""
        if self.employee_id and self.date_from and self.holiday_status_id:
            if self.holiday_status_id.is_paid:
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

    @api.depends('date_from', 'date_to', 'resource_calendar_id', 'holiday_status_id.request_unit',
                 'holiday_status_id.is_calendar_days', 'request_date_from', 'request_date_to')
    def _compute_duration(self):
        calendar_days_leaves = self.filtered(
            lambda l: l.holiday_status_id and l.holiday_status_id.is_calendar_days
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

    @api.depends('calendar_days', 'average_daily_salary', 'holiday_status_id.is_paid')
    def _compute_vacation_pay(self):
        for leave in self:
            if leave.holiday_status_id.is_paid and leave.average_daily_salary:
                leave.vacation_pay_amount = leave.calendar_days * leave.average_daily_salary
            else:
                leave.vacation_pay_amount = 0.0

    @api.depends('employee_id', 'holiday_status_id', 'vacation_year', 'request_date_from')
    def _compute_remaining_before(self):
        """Computes the balance before the start of a specific leave in chronological order."""
        for leave in self:
            if not leave.employee_id or not leave.holiday_status_id:    
                leave.remaining_days_before = 0
                continue

            # Resolve year from vacation_year first, then fall back to
            # request_date_from. Without either, we cannot compute.
            year = leave.vacation_year or (
                leave.request_date_from.year if leave.request_date_from else False
            )
            if not year:
                leave.remaining_days_before = 0
                continue
             
            # Get the initial total balance for the year (Entitled + Carried Over)
            balance = self.env['hr.vacation.balance'].search([
                ('employee_id', '=', leave.employee_id.id),
                ('leave_type_id', '=', leave.holiday_status_id.id),
                ('year', '=', year),
            ], limit=1)
        
            total_available = balance.total_available if balance else (leave.holiday_status_id.annual_days or 0)

            # Find leaves of the same year. Chronological mode (request_date_from
            # set on the leave): only earlier-starting leaves. Year-aggregate
            # fallback (no request_date_from yet — e.g. a draft in the form
            # with only vacation_year): all year's leaves so the value reflects
            # "annual_days − already used/planned this year".
            domain = [
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', '=', leave.holiday_status_id.id),
                ('state', 'not in', ['cancel', 'refuse']), # Count both planned and approved leaves
                '|', ('vacation_year', '=', year),
                     '&', ('request_date_from', '>=', f'{year}-01-01'),
                          ('request_date_from', '<=', f'{year}-12-31'),
            ]
            # Apply the chronological "earlier than this leave" filter ONLY
            # when the leave's start date falls within (or after) the year
            # we are computing. For a brand-new draft, Odoo's hr.leave fills
            # request_date_from with today() by default — applying the
            # filter in that case would exclude future-year leaves and break
            # the year-aggregate fallback.
            year_start = fields.Date.from_string(f'{year}-01-01')
            if leave.request_date_from and leave.request_date_from >= year_start:
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
        'state', 'employee_id', 'holiday_status_id',
        'date_from', 'date_to',
        'request_date_from', 'request_date_to',
        'vacation_year',
    })

    def _balance_keys(self):
        """Return (employee_id, leave_type_id, year) tuples identifying
        the hr.vacation.balance rows touched by leaves in self."""
        keys = set()
        for leave in self:
            emp = leave.employee_id.id
            ltype = leave.holiday_status_id.id
            if not emp or not ltype:
                continue
            years = set()
            if leave.vacation_year:
                years.add(leave.vacation_year)
            if leave.request_date_from:
                years.add(leave.request_date_from.year)
            if leave.request_date_to:
                years.add(leave.request_date_to.year)
            for y in years:
                keys.add((emp, ltype, y))
        return keys

    @api.model
    def _recompute_balances_for_keys(self, keys):
        if not keys:
            return
        Balance = self.env['hr.vacation.balance'].sudo()
        balances = Balance.browse()
        for emp, ltype, y in keys:
            balances |= Balance.search([
                ('employee_id', '=', emp),
                ('leave_type_id', '=', ltype),
                ('year', '=', y),
            ])
        if balances:
            balances.invalidate_recordset([
                'used_days', 'planned_days',
                'total_available', 'remaining_days',
            ])
            balances._compute_used_days()
            balances._compute_totals()

    def _recompute_subsequent_leaves(self):
        """Helper method: forcibly updates the balance for leaves that come AFTER the current one."""
        for leave in self:
            if not leave.employee_id or not leave.holiday_status_id or not leave.request_date_from:
                continue
            year = leave.vacation_year or leave.request_date_from.year
           
            # Find all leaves with a date greater than the date of the changed leave
            subsequent_leaves = self.env['hr.leave'].search([
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', '=', leave.holiday_status_id.id),
                ('request_date_from', '>', leave.request_date_from),
                '|', ('vacation_year', '=', year),
                     '&', ('request_date_from', '>=', f'{year}-01-01'),
                          ('request_date_from', '<=', f'{year}-12-31'),
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
        payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', '=', 'done'),
        ])

        if not payslips:
            # Fallback to version wage (Odoo 19 uses version_ids instead of contract_id)
            version = self.employee_id.current_version_id
            if version and version.wage:
                return round(version.wage / 29.3, 2)
            return 0.0

        # Calculate total earnings from payslip lines
        total_earnings = 0.0
        excluded_days = 0

        for payslip in payslips:
            # Check if payslip has line_ids (Odoo payroll module structure)
            if hasattr(payslip, 'line_ids') and payslip.line_ids:
                for line in payslip.line_ids:
                    # Check if salary rule has is_basic_salary attribute
                    if hasattr(line, 'salary_rule_id') and line.salary_rule_id:
                        rule = line.salary_rule_id
                        # Include if marked as basic salary or if it's a base category
                        if getattr(rule, 'is_basic_salary', False) or \
                           getattr(rule, 'category_id', False) and \
                           rule.category_id.code in ('BASIC', 'ALW', 'GROSS'):
                            total_earnings += line.total or 0
                    else:
                        # Fallback: include all positive lines
                        total_earnings += max(0, line.total or 0)
            else:
                # Fallback: use gross_salary if available, else net
                if hasattr(payslip, 'gross_salary'):
                    total_earnings += payslip.gross_salary or 0
                elif hasattr(payslip, 'net_wage'):
                    total_earnings += payslip.net_wage or 0

        # Calculate excluded days from sick leave and unpaid leave in the period
        sick_leave_type = self.env['hr.leave.type'].search([
            ('ua_leave_category', '=', 'sick')
        ], limit=1)
        unpaid_leave_type = self.env['hr.leave.type'].search([
            ('ua_leave_category', '=', 'unpaid')
        ])

        excluded_leave_types = sick_leave_type.ids + unpaid_leave_type.ids
        if excluded_leave_types:
            excluded_leaves = self.env['hr.leave'].search([
                ('employee_id', '=', self.employee_id.id),
                ('holiday_status_id', 'in', excluded_leave_types),
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
