from datetime import date
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

class HrVacationBalance(models.Model):
    _name = 'hr.vacation.balance'
    _description = 'Vacation Balance'
    _order = 'period_start desc, employee_id'

    # Record name is the period range. Odoo's base display_name is computed
    # from _rec_name on the fly, so there is no stored display_name to keep
    # in sync (and no employee name to leak into the label).
    _rec_name = 'period_label'


    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        check_company=True
    )
    leave_type_id = fields.Many2one(
        'hr.work.entry.type',
        string='Leave Type',
        required=True,
        domain="[('ua_leave_category', '!=', False)]"
    )
    period_type = fields.Selection(
        related='leave_type_id.period_type',
        store=True,
        index=True,
    )
    period_start = fields.Date(
        string='Period Start',
        required=True,
        index=True,
    )
    period_end = fields.Date(
        string='Period End',
        required=True,
    )
    period_index = fields.Integer(
        string='Period #',
        help='Calendar year for calendar periods; sequential work-year '
             'number from hire date for work periods.'
    )
    period_label = fields.Char(
        string='Period',
        compute='_compute_period_label',
        store=True,
    )
    year = fields.Integer(
        string='Year',
        compute='_compute_year',
        store=True,
        index=True,
        help='Start year of the accounting period. Kept for backward '
             'compatibility with year-based filters and reports.'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    entitled_days = fields.Float(
        string='Entitled Days',
        compute='_compute_entitled_days',
        store=True,
        readonly=False,
        precompute=True,
        help='Days entitled for the year. Defaults to leave type annual_days; '
             'can be overridden manually (e.g. proportional for mid-year hires).'
    )
    carried_over = fields.Float(
        string='Carried Over',
        help='Days carried from previous year'
    )
    total_available = fields.Float(
        string='Total Available',
        compute='_compute_totals',
        store=True
    )
    
    used_days = fields.Float(
        string='Used Days',
        compute='_compute_used_days',
        store=True
    )
    planned_days = fields.Float(
        string='Planned Days',
        compute='_compute_used_days',
        store=True
    )
    remaining_days = fields.Float(
        string='Remaining Days',
        compute='_compute_totals',
        store=True
    )
    
    @api.model
    def _get_period_for(self, employee, leave_type, ref_date):
        """Return (period_start, period_end, period_index) of the accounting
        period containing ref_date for the given employee and leave type.

        Work-year types delegate to hr.employee._get_work_year_for_date;
        calendar types return Jan 1 – Dec 31 with period_index = year.
        Returns (False, False, 0) for work types without a hire anchor, or
        for any period that ends before the employee's hire date (no leave
        or balance can exist before the person was hired).
        """
        if leave_type.period_type == 'work':
            return employee._get_work_year_for_date(ref_date)
        hire = self._employee_hire_anchor(employee)
        if hire and date(ref_date.year, 12, 31) < hire:
            # The whole calendar year precedes the hire date.
            return (False, False, 0)
        return (date(ref_date.year, 1, 1), date(ref_date.year, 12, 31), ref_date.year)

    @api.model
    def _get_or_create_period(self, employee, leave_type, ref_date):
        """Return the accounting period (hr.vacation.balance) that contains
        ref_date for this employee/leave type, creating it if it does not
        exist yet. A newly created period inherits its carried_over days from
        the previous period in the chain. Returns an empty recordset when the
        period cannot be resolved (e.g. a work-year type without a hire
        anchor), so callers can leave the leave unlinked in that edge case."""
        if not employee or not leave_type or not ref_date:
            return self.browse()
        start, end, index = self._get_period_for(employee, leave_type, ref_date)
        if not start:
            return self.browse()
        balance = self.search([
            ('employee_id', '=', employee.id),
            ('leave_type_id', '=', leave_type.id),
            ('period_start', '=', start),
        ], limit=1)
        if balance:
            return balance
        prev = self.search([
            ('employee_id', '=', employee.id),
            ('leave_type_id', '=', leave_type.id),
            ('period_index', '=', index - 1),
        ], limit=1)
        return self.create({
            'employee_id': employee.id,
            'leave_type_id': leave_type.id,
            'period_start': start,
            'period_end': end,
            'period_index': index,
            'entitled_days': leave_type.annual_days,
            'carried_over': (
                self._allowed_carryover(leave_type, prev.remaining_days)
                if prev else 0),
            'company_id': employee.company_id.id or self.env.company.id,
        })

    @api.model
    def _ensure_periods_up_to(self, employee, leave_type, up_to_date,
                              select_date=None):
        """Create every missing accounting period for (employee, leave_type)
        from the employee's hire anchor up to up_to_date, refresh the carry-over
        chain, and return the period that contains select_date (default:
        up_to_date). Empty recordset when it cannot be resolved (e.g. a
        work-year type without a hire anchor).

        Callers backfill up to max(today, leave_start) — so every past period
        keeps a record — while selecting the period the leave's FIRST DAY falls
        into, which may be a future period when a vacation is planned ahead."""
        if not employee or not leave_type:
            return self.browse()
        self._generate_period_chain(employee, leave_type, up_to_date)
        chain = self.search([
            ('employee_id', '=', employee.id),
            ('leave_type_id', '=', leave_type.id),
        ])
        if chain:
            chain._recompute_carryover_chain()
        return self._get_or_create_period(
            employee, leave_type, select_date or up_to_date)

    @api.model
    def _allowed_carryover(self, leave_type, prev_remaining):
        """Days carried into the next period.

        Transferability governs ALL movement across periods. A NON-transferable
        type carries nothing forward — neither positive unused days nor a
        negative over-use debt: its periods stand on their own, so a deficit in
        one period does not reduce the next.

        For a TRANSFERABLE type:
          * a NEGATIVE balance — more days taken than were available (e.g. 26
            days used against a 24-day entitlement, leaving -2) — is carried
            forward in full: an over-use debt cannot be forfeited and must
            reduce the next period's Total Available (24 + (-2) = 22);
          * positive unused days are carried up to `max_transfer_days` (or in
            full when no cap is set); days above the cap are forfeited (surfaced
            as a non-blocking warning on the leave, not enforced here)."""
        if not leave_type.is_transferable:
            return 0
        if prev_remaining <= 0:
            return prev_remaining
        if leave_type.max_transfer_days:
            return min(prev_remaining, leave_type.max_transfer_days)
        return prev_remaining

    @api.model
    def _employee_hire_anchor(self, employee):
        """Hire date that bounds accounting periods, blocks pre-hire
        leaves/periods and starts the period-chain backfill.

        Single source: employee._get_vacation_anchor_date(), i.e. hire_date
        (itself derived from hr.version.contract_date_start) unless a work
        year was carried over from another company — so no separate version
        fallback is needed here or in hr.employee._get_work_year_for_date."""
        return employee._get_vacation_anchor_date() if employee else False

    @api.model
    def _ref_date_for_year(self, year):
        """Pick a reference date inside the requested year to resolve
        the accounting period: today when generating for the current year,
        end of year for past years, start of year for future years."""
        today = fields.Date.today()
        if year == today.year:
            return today
        if year < today.year:
            return date(year, 12, 31)
        return date(year, 1, 1)

    @api.depends('period_start')
    def _compute_year(self):
        for rec in self:
            rec.year = rec.period_start.year if rec.period_start else 0

    @api.depends('period_start', 'period_end')
    def _compute_period_label(self):
        # Date range only, for both work and calendar periods
        # (e.g. "01.07.2025 – 30.06.2026").
        for rec in self:
            if rec.period_start and rec.period_end:
                rec.period_label = '%s – %s' % (
                    rec.period_start.strftime('%d.%m.%Y'),
                    rec.period_end.strftime('%d.%m.%Y'),
                )
            else:
                rec.period_label = ''

    @api.depends('leave_type_id', 'period_start', 'period_end')
    def _compute_entitled_days(self):
        for rec in self:
            if not rec.leave_type_id or rec.entitled_days:
                continue
            annual = rec.leave_type_id.annual_days or 0
            entitled = annual
            # Shortened period (e.g. termination mid work-year): prorate.
            if rec.period_start and rec.period_end:
                span_days = (rec.period_end - rec.period_start).days + 1
                if span_days < 365:
                    entitled = round(annual * span_days / 365.0, 2)
            rec.entitled_days = entitled

    @api.model
    def default_get(self, fields_list):
        """Prefill the balance from the leave form's context.

        The Vacation Period field on hr.leave passes default_employee_id,
        default_leave_type_id and default_period_year; from those we can
        resolve the whole accounting period (dates, index, company) up
        front, so the "create period" dialog opens fully populated.
        """
        res = super().default_get(fields_list)
        ctx = self.env.context
        emp_id = res.get('employee_id') or ctx.get('default_employee_id')
        lt_id = res.get('leave_type_id') or ctx.get('default_leave_type_id')
        if emp_id and lt_id and not res.get('period_start'):
            employee = self.env['hr.employee'].browse(emp_id)
            leave_type = self.env['hr.work.entry.type'].browse(lt_id)
            ref_year = ctx.get('default_period_year') or fields.Date.today().year
            start, end, index = self._get_period_for(
                employee, leave_type, self._ref_date_for_year(ref_year))
            if not start:
                # Work-year type without a hire anchor: calendar fallback
                start, end, index = (
                    date(ref_year, 1, 1), date(ref_year, 12, 31), ref_year)
            res.setdefault('period_start', start)
            res.setdefault('period_end', end)
            res.setdefault('period_index', index)
            if 'company_id' in fields_list and not res.get('company_id'):
                res['company_id'] = employee.company_id.id or self.env.company.id
        return res

    @api.onchange('company_id')
    def _onchange_company_id(self):
        # Only clear a now-incompatible employee on a genuine company
        # switch — never wipe values prefilled from the leave form.
        # The leave type itself is country-scoped since Odoo 20, so it can
        # no longer be incompatible with the company.
        if (self.employee_id and self.employee_id.company_id
                and self.company_id
                and self.employee_id.company_id != self.company_id):
            self.employee_id = False

    @api.onchange('employee_id', 'leave_type_id')
    def _onchange_period_defaults(self):
        """Prefill the accounting period once employee and type are chosen."""
        for rec in self:
            if not rec.employee_id or not rec.leave_type_id or rec.period_start:
                continue
            ref_year = self.env.context.get('default_period_year')
            ref_date = (self._ref_date_for_year(ref_year) if ref_year
                        else fields.Date.context_today(self))
            start, end, index = self._get_period_for(
                rec.employee_id, rec.leave_type_id, ref_date)
            if not start:
                # Work-year type without hire anchor: calendar fallback
                start, end, index = (
                    date(ref_date.year, 1, 1), date(ref_date.year, 12, 31),
                    ref_date.year)
            rec.period_start = start
            rec.period_end = end
            rec.period_index = index

    @api.constrains('period_start', 'period_end')
    def _check_period_bounds(self):
        for rec in self:
            if rec.period_start and rec.period_end and rec.period_start > rec.period_end:
                raise ValidationError(_('Period start must be before period end.'))

    @api.constrains('period_end', 'employee_id', 'leave_type_id')
    def _check_period_after_hire(self):
        """No accounting period may end before the employee was hired."""
        for rec in self:
            if not rec.employee_id or not rec.period_end:
                continue
            hire = self._employee_hire_anchor(rec.employee_id)
            if hire and rec.period_end < hire:
                raise ValidationError(_(
                    'The accounting period (ending %(end)s) precedes the hire '
                    'date of %(employee)s (%(hire)s). A vacation period cannot '
                    'start before the employee was hired.',
                    end=rec.period_end.strftime('%d.%m.%Y'),
                    employee=rec.employee_id.name,
                    hire=hire.strftime('%d.%m.%Y'),
                ))

    @api.depends('entitled_days', 'carried_over', 'used_days')
    def _compute_totals(self):
        for rec in self:
            rec.total_available = (rec.entitled_days or 0) + (rec.carried_over or 0)
            rec.remaining_days = rec.total_available - (rec.used_days or 0)

    def _charged_leaves_domain(self):
        """Domain matching the leaves charged to this period.

        Primary rule: a leave is charged to the period it is EXPLICITLY linked
        to (vacation_balance_id), chosen manually on the leave/order form —
        regardless of whether its dates fall inside the period bounds (HR may
        record a past-period leave with current dates). The days counted are
        exactly those entered on the leave (calendar_days).

        Safety net: a leave of this employee and leave type that has NO period
        linked yet still counts against the period its start date falls into.
        create()/_ensure_vacation_period() normally fill the link, but a leave
        can slip through (import, a write clearing the field, a type whose
        period could not be resolved when it was created). Without this
        fallback such a leave would be charged to NO period at all, understating
        used_days and overstating the remaining days. This mirrors
        hr.leave._period_domain, which already treats unlinked leaves this way
        for the per-leave Balance Before/After chain."""
        self.ensure_one()
        return [
            ('employee_id', '=', self.employee_id.id),
            ('work_entry_type_id', '=', self.leave_type_id.id),
            '|', ('vacation_balance_id', '=', self.id),
                 '&', ('vacation_balance_id', '=', False),
                      '&', ('request_date_from', '>=', self.period_start),
                           ('request_date_from', '<=', self.period_end),
        ]

    @api.depends('employee_id', 'leave_type_id', 'period_start', 'period_end')
    def _compute_used_days(self):
        HrLeave = self.env['hr.leave']
        for rec in self:
            if (not rec.employee_id or not rec.leave_type_id
                    or not rec.period_start or not rec.period_end):
                rec.used_days = 0
                rec.planned_days = 0
                continue

            base_domain = rec._charged_leaves_domain()

            used_leaves = HrLeave.search(base_domain + [('state', '=', 'validate')])
            rec.used_days = sum(used_leaves.mapped('calendar_days'))

            planned_leaves = HrLeave.search(base_domain + [
                ('state', 'in', ('draft', 'confirm', 'validate1')),
            ])
            rec.planned_days = sum(planned_leaves.mapped('calendar_days'))

    @api.model
    def _generate_period_chain(self, employee, leave_type, up_to_date=None):
        """Create every missing accounting period for (employee, leave_type)
        from the employee's first period (on/after the hire anchor) up to the
        period containing up_to_date (default: today).

        Filling the gaps is what lets carry-over cascade across a year in
        which no leave was taken: without the missing year's row, its unused
        entitlement is silently dropped instead of rolling into the next
        period. Returns the balances that were created (carried_over is left
        to the carry-over chain). Yields nothing when the period cannot be
        resolved (e.g. a work-year type without a hire anchor)."""
        if not employee or not leave_type:
            return self.browse()
        if up_to_date is None:
            up_to_date = fields.Date.today()
        # Walk from the employment anchor forward so the whole history is
        # filled; with no anchor at all we can only handle the current period.
        cursor = self._employee_hire_anchor(employee) or up_to_date
        created = self.browse()
        guard = 0
        while cursor <= up_to_date and guard < 200:
            guard += 1
            start, end, index = self._get_period_for(
                employee, leave_type, cursor)
            if not start:
                break
            # Skip when an existing balance already OVERLAPS this range, not
            # only when one has the exact same period_start. A legacy or
            # differently-anchored row (e.g. a calendar-year period, or one
            # created before hire_date was corrected) covers the same span
            # with a different start; matching on start alone would create a
            # canonical period on top of it — a visible duplicate.
            overlaps = self.search_count([
                ('employee_id', '=', employee.id),
                ('leave_type_id', '=', leave_type.id),
                ('period_start', '<=', end),
                ('period_end', '>=', start),
            ])
            if not overlaps:
                created |= self.create({
                    'employee_id': employee.id,
                    'leave_type_id': leave_type.id,
                    'period_start': start,
                    'period_end': end,
                    'period_index': index,
                    'company_id': (employee.company_id.id
                                   or self.env.company.id),
                })
            cursor = end + relativedelta(days=1)
        return created

    def generate_balances(self, year=None, leave_types=None, up_to_date=None):
        """Backfill accounting periods for all employees so carry-over
        cascades across the full history.

        Runs for transferable, day-accruing leave types that are additionally
        flagged with ua_auto_calc_balance; for each of them, every period from
        the employee's hire anchor up to the reference date is created if
        missing — so a year with no leave taken no longer breaks the carry-over
        chain. Employees without a hire anchor get only the currently
        resolvable period (work-year types: none).

        The reference date is `up_to_date` when given (used by the "as of a
        date" summary report), otherwise the reference date of `year`, or today.
        """
        if up_to_date is None:
            up_to_date = self._ref_date_for_year(year) if year else fields.Date.today()
 
        domain = []
        if 'contract_id' in self.env['hr.employee']._fields:
            domain.append(('contract_id.state', '=', 'open'))
        employees = self.env['hr.employee'].search(domain)

        if leave_types is None:
            # Types whose unused days roll forward AND that the user opted in
            # to auto-calculate balances for.
            leave_types = self.env['hr.work.entry.type'].search([
                ('is_transferable', '=', True),
                ('annual_days', '>', 0),
                ('ua_auto_calc_balance', '=', True),
            ])

        created = self.browse()
        for leave_type in leave_types:
            for employee in employees:
                # No cross-company guard any more: Odoo 20 scopes
                # hr.work.entry.type by country, not by company, so every
                # company shares one annual_basic type and an employee can
                # only ever get one balance per type and period.
                created |= self._generate_period_chain(
                    employee, leave_type, up_to_date)
        # Refresh the rollups for EVERY period of the processed types back to
        # the hire date — not only the newly created rows — so "Recalculate"
        # actually re-runs used/planned/remaining and the carry-over chain for
        # all historical periods, not just the current one.
        if leave_types and employees:
            all_balances = self.search([
                ('employee_id', 'in', employees.ids),
                ('leave_type_id', 'in', leave_types.ids),
            ])
            if all_balances:
                all_balances.invalidate_recordset([
                    'used_days', 'planned_days',
                    'total_available', 'remaining_days',
                ])
                all_balances._compute_used_days()
                all_balances._compute_totals()
                all_balances._recompute_carryover_chain()
        return created

    def _link_related_leaves(self):
        """Attach unlinked leaves that fall into this balance's period.

        When a balance row appears after its leaves (manual creation,
        generate_balances), the leaves' vacation_balance_id was computed
        to False — recompute it now so rollups and per-leave chains see
        the new period.
        """
        Leave = self.env['hr.leave']
        for balance in self:
            leaves = Leave.search([
                ('employee_id', '=', balance.employee_id.id),
                ('work_entry_type_id', '=', balance.leave_type_id.id),
                ('vacation_balance_id', '=', False),
                ('request_date_from', '>=', balance.period_start),
                ('request_date_from', '<=', balance.period_end),
            ])
            if leaves:
                # Attach only leaves that still have no period (legacy/migrated)
                # to this newly created period; leaves keep a manually chosen
                # period once set.
                leaves.vacation_balance_id = balance.id

    def _recompute_carryover_chain(self):
        """Propagate carry-over across each (employee, leave_type) period
        chain: every period after the first inherits the previous period's
        remaining days, capped by the leave type's transfer rules
        (_allowed_carryover — non-transferable types carry nothing, and
        max_transfer_days limits the rest).

        Lets a back-dated period feed its unused days into the following
        periods (e.g. a leave entered late for last year updates this
        year's Carried Over). The first period keeps its own (possibly
        manual) carried_over untouched.
        """
        seen = set()
        for rec in self:
            if not rec.employee_id or not rec.leave_type_id:
                continue
            key = (rec.employee_id.id, rec.leave_type_id.id)
            if key in seen:
                continue
            seen.add(key)
            chain = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
            ], order='period_start')
            prev = None
            for bal in chain:
                if prev is not None:
                    allowed = self._allowed_carryover(
                        bal.leave_type_id, prev.remaining_days)
                    if bal.carried_over != allowed:
                        bal.carried_over = allowed
                prev = bal

    def _recompute_related_leaves(self):
        """
        Helper method to force recomputation of remaining days for all leaves
        associated with this balance record.
        """
        for balance in self:
            leaves = self.env['hr.leave'].search([
                ('employee_id', '=', balance.employee_id.id),
                ('work_entry_type_id', '=', balance.leave_type_id.id),
                '|', ('vacation_balance_id', '=', balance.id),
                     '&', ('vacation_balance_id', '=', False),
                          '&', ('request_date_from', '>=', balance.period_start),
                               ('request_date_from', '<=', balance.period_end),
            ])
            if leaves:
                # Sort chronologically to ensure cascading subtraction is correct
                sorted_leaves = leaves.sorted(key=lambda l: l.request_date_from or fields.Date.today())
                sorted_leaves._compute_remaining_before()
                sorted_leaves._compute_remaining_after()

    @api.model_create_multi
    def create(self, vals_list):
        # Backward-compat: derive the accounting period when the caller
        # still passes only 'year' (transfer wizard, legacy code, tests).
        for vals in vals_list:
            if vals.get('period_start') and vals.get('period_end'):
                continue
            employee = self.env['hr.employee'].browse(vals.get('employee_id'))
            leave_type = self.env['hr.work.entry.type'].browse(vals.get('leave_type_id'))
            year = vals.get('year') or fields.Date.today().year
            ref_date = self._ref_date_for_year(year)
            # A reference date earlier in the year than the hire anniversary
            # resolves no work year at all (the employee was not hired yet on
            # that day) and would drop the balance to the calendar fallback
            # below. This happens whenever a period is created for a year the
            # employee is hired into — e.g. the transfer wizard carrying
            # vacation days into a future-dated hire. Start the lookup at the
            # hire anchor instead: same year, but inside the employment.
            hire = self._employee_hire_anchor(employee)
            if hire and hire.year == ref_date.year and ref_date < hire:
                ref_date = hire
            start, end, index = self._get_period_for(employee, leave_type, ref_date)
            if not start:
                # Work-year type without hire anchor: calendar fallback
                start, end, index = (
                    date(year, 1, 1), date(year, 12, 31), year)
            vals.setdefault('period_start', start)
            vals.setdefault('period_end', end)
            vals.setdefault('period_index', index)
        balances = super().create(vals_list)
        # Attach pre-existing leaves, then refresh rollups so used_days
        # reflects them before the carry-over is propagated.
        balances._link_related_leaves()
        balances.invalidate_recordset([
            'used_days', 'planned_days', 'total_available', 'remaining_days',
        ])
        balances._compute_used_days()
        balances._compute_totals()
        balances._recompute_related_leaves()
        # A new (possibly back-dated) period may change carry-over downstream.
        balances._recompute_carryover_chain()
        return balances

    def write(self, vals):
        res = super().write(vals)
        # Trigger recomputation only when base days or the period are modified
        if any(field in vals for field in [
                'entitled_days', 'carried_over', 'period_start', 'period_end',
                'employee_id', 'leave_type_id']):
            self._recompute_related_leaves()
        return res

    _unique_employee_id_leave_type_id_period_start = models.Constraint(
        'unique(employee_id, leave_type_id, period_start)',
        'Balance for this employee, leave type and period already exists!',
    )

    # NOTE: carry-over is no longer hard-blocked. Transfer limits differ per
    # leave type (is_transferable / max_transfer_days) and are applied when
    # computing carried_over (see _allowed_carryover). Days that cannot be
    # transferred are surfaced to the user as a non-blocking warning on the
    # leave (hr.leave._carryover_warning_message), never enforced here.

    def calculate_compensation(self, termination_date=None, is_termination=True):
        """Calculate compensation for unused vacation.

        Args:
            termination_date: Date of termination/calculation (defaults to today)
            is_termination: If True, compensate all unused days (on termination).
                           If False, only compensate days over 24 (without termination).

        Returns:
            float: Compensation amount for unused vacation days
            
        Per Ukrainian law:
        - On termination: all unused days are compensated
        - Without termination: only days over 24 can be compensated,
          and employee must have used at least 24 days in current year
        """
        self.ensure_one()

        if not self.employee_id or not self.remaining_days:
            return 0.0

        if termination_date is None:
            termination_date = fields.Date.today()

        compensable_days = self.remaining_days
        
        if not is_termination:
            min_annual_days = self.leave_type_id.annual_days or 24
            if self.used_days < min_annual_days:
                return 0.0
            compensable_days = max(0, self.remaining_days - min_annual_days)
            if compensable_days <= 0:
                return 0.0

        # Get average daily salary using hr.leave calculation
        leave = self.env['hr.leave'].new({
            'employee_id': self.employee_id.id,
            'date_from': termination_date,
        })
        avg_salary = leave._calculate_average_salary()

        if avg_salary <= 0:
            return 0.0

        compensation = compensable_days * avg_salary
        return round(compensation, 2)

    def action_calculate_compensation(self):
        """Action to calculate and display compensation amount."""
        self.ensure_one()
        compensation = self.calculate_compensation()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vacation Compensation'),
                'message': _('Compensation for %(days)s unused days: %(amount).2f UAH', days=self.remaining_days, amount=compensation),
                'type': 'success',
                'sticky': False,
            }
        }

    def _reanchor_period(self):
        """Fix work-year bounds that don't match the employee's hire
        anniversary — e.g. a balance created or migrated while the
        employee had no hire anchor yet (calendar fallback applied), or
        whose hire_date was corrected afterwards.
        Keeps the row's original start year as the anniversary year so
        `year` and year-based reports stay stable. Skips silently when
        no anchor is available or the target period already exists.
        """
        self.ensure_one()
        if self.period_type != 'work' or not self.employee_id:
            return
        anchor = self._employee_hire_anchor(self.employee_id)
        if not anchor:
            return
        index = (self.year or anchor.year) - anchor.year + 1
        if index < 1:
            return
        start = anchor + relativedelta(years=index - 1)
        end = anchor + relativedelta(years=index) - relativedelta(days=1)
        if start == self.period_start:
            return
        conflict = self.search_count([
            ('employee_id', '=', self.employee_id.id),
            ('leave_type_id', '=', self.leave_type_id.id),
            ('period_start', '=', start),
            ('id', '!=', self.id),
        ])
        if conflict:
            return
        self.write({
            'period_start': start,
            'period_end': end,
            'period_index': index,
        })

    def action_recalculate(self):
        for rec in self:
            rec._reanchor_period()
            if rec.leave_type_id and not rec.entitled_days:
                rec.entitled_days = rec.leave_type_id.annual_days or 0
        self.invalidate_recordset([
            'used_days', 'planned_days', 'total_available', 'remaining_days',
        ])
        self._compute_used_days()
        self._compute_totals()
        self._recompute_carryover_chain()
        return True

    def action_recalculate_all(self):
        """
        Recalculate or generate vacation balances for the current year
        for all active employees.
        """
        current_year = fields.Date.today().year
        self.generate_balances(year=current_year)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recalculation Complete'),
                'message': _(
                    'Vacation balances for %(year)s have been updated for all '
                    'active employees.', year=current_year),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }
