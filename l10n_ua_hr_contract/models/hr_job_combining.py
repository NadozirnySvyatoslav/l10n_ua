from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class HrJobCombining(models.Model):
    _name = 'hr.job.combining'
    _description = 'Job Combining'
    _order = 'date_from desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='New'
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True
    )
    version_id = fields.Many2one(
        'hr.version',
        string='Employee Version',
        required=True,
        tracking=True,
        domain="[('employee_id', '=', employee_id), ('contract_date_start', '!=', False)]"
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='version_id.company_id',
        store=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='version_id.currency_id'
    )

    combined_job_id = fields.Many2one(
        'hr.job',
        string='Combined Position',
        required=True,
        tracking=True
    )
    combined_department_id = fields.Many2one(
        'hr.department',
        string='Combined Department',
        tracking=True
    )
    combined_rate = fields.Float(
        string='Частка ставки',
        default=0.5,
        tracking=True,
        help='Частка штатної одиниці суміщуваної посади, яку займає '
             'працівник (0.5 = півставки). Споживається у штатному розписі '
             'нарівні з основними працівниками.'
    )

    date_from = fields.Date(
        string='Date From',
        required=True,
        tracking=True
    )
    date_to = fields.Date(
        string='Date To',
        tracking=True
    )

    # Compensation
    surcharge_type = fields.Selection([
        ('percent', 'Percent of Salary'),
        ('fixed', 'Fixed Amount'),
    ], string='Surcharge Type', default='percent', required=True)

    surcharge_percent = fields.Float(
        string='Surcharge %',
        default=50.0,
        help='Percentage of main salary as surcharge'
    )
    surcharge_amount = fields.Monetary(
        string='Surcharge Amount',
        currency_field='currency_id',
        help='Fixed surcharge amount'
    )
    calculated_surcharge = fields.Monetary(
        string='Calculated Surcharge',
        compute='_compute_calculated_surcharge',
        store=True,
        currency_field='currency_id'
    )

    # Order references
    order_number = fields.Char(string='Order Number', required=True, tracking=True)
    order_date = fields.Date(string='Order Date', required=True)
    cancellation_order_number = fields.Char(string='Cancellation Order')
    cancellation_order_date = fields.Date(string='Cancellation Order Date')

    # Related allowance
    allowance_id = fields.Many2one(
        'hr.version.allowance',
        string='Version Allowance',
        help='Automatically created allowance for this job combining'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Notes')

    @api.depends('employee_id', 'combined_job_id', 'order_number')
    def _compute_display_name(self):
        for record in self:
            if record.employee_id and record.combined_job_id:
                record.display_name = f"{record.employee_id.name} - {record.combined_job_id.name} ({record.order_number or 'New'})"
            else:
                record.display_name = record.name or 'New'

    # Fields that decide whether a combination occupies a combined position,
    # and on which dates. `version_id` is among them because `company_id` is a
    # stored related on it: moving the combination to another employee's
    # version can move it to another company.
    _STAFFING_OCCUPANCY_FIELDS = frozenset({
        'state', 'date_from', 'date_to', 'combined_rate',
        'combined_job_id', 'combined_department_id', 'version_id',
    })

    # Everything the allowance keeps a copy of. Payroll reads the allowance
    # and never this model, so any of these left behind is a surcharge that
    # disagrees with the order it was issued under.
    _ALLOWANCE_FIELDS = frozenset({
        'version_id', 'date_from', 'date_to', 'combined_job_id',
        'surcharge_type', 'surcharge_percent', 'surcharge_amount',
    })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.job.combining') or 'New'
        records = super().create(vals_list)
        records._recompute_staffing()
        return records

    def write(self, vals):
        """Every route into the occupancy, not just the two buttons.

        `action_activate` and `action_cancel` used to call the recount
        themselves, which covered the state changes and nothing else. Once the
        dates of a combination decide the answer, editing `date_from`,
        `date_to` or `combined_rate` on an active one moves the occupancy just
        as surely — and left `filled_units` stale for good, because no
        `@api.depends` reaches here. `hr.version` has carried this hook since
        the same change; this is the other half of it.

        The buttons need no call of their own any more: assigning a field on a
        saved record goes through `write` (`Field.__set__`).
        """
        touches_occupancy = not self._STAFFING_OCCUPANCY_FIELDS.isdisjoint(vals)
        previous = self._staffing_positions() if touches_occupancy else ()
        result = super().write(vals)
        if touches_occupancy:
            self._recompute_staffing(previous)
        if not self._ALLOWANCE_FIELDS.isdisjoint(vals):
            self._sync_allowance()
        return result

    def unlink(self):
        previous = self._staffing_positions()
        result = super().unlink()
        self._recompute_staffing_positions(previous)
        return result

    @api.depends('surcharge_type', 'surcharge_percent', 'surcharge_amount', 'version_id.wage')
    def _compute_calculated_surcharge(self):
        for record in self:
            if record.surcharge_type == 'percent':
                record.calculated_surcharge = (record.version_id.wage or 0) * (record.surcharge_percent or 0) / 100
            else:
                record.calculated_surcharge = record.surcharge_amount or 0

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_to and record.date_from > record.date_to:
                raise ValidationError('End date must be after start date!')

    @api.constrains('combined_rate')
    def _check_combined_rate(self):
        for record in self:
            if record.combined_rate <= 0 or record.combined_rate > 1:
                raise ValidationError(
                    'Частка ставки суміщення має бути в межах (0; 1].')

    def _staffing_positions(self):
        return {(record.company_id.id, record.combined_department_id.id,
                 record.combined_job_id.id) for record in self}

    def _recompute_staffing(self, previous=()):
        """Have the staffing table count the combined positions again.

        `filled_units` has no `@api.depends` path to a combination, so a
        change has to be reported here by hand — for the position as it was
        and as it now is, since moving a combination between two posts frees
        one and fills the other.

        Through `add_to_compute`, not by calling the compute directly. The
        direct call runs under the rights of whoever is writing and stores
        what it produces, and the count reads `contract_date_*`, which core
        keeps behind hr.group_hr_manager: an officer without that group would
        get an AccessError where everything used to work quietly. Going
        through the ORM gets the field the `compute_sudo` it is entitled to.
        """
        self._recompute_staffing_positions(
            set(previous) | self._staffing_positions())

    def _recompute_staffing_positions(self, positions):
        Staffing = self.env.get('hr.staffing.table')
        if Staffing is None:
            return
        Staffing._recompute_occupancy(positions)

    def _allowance_values(self):
        """What the allowance keeps a copy of: whose, how much, and when.

        One mapping, read both when the allowance is created and whenever the
        combination changes afterwards. A second copy of the rule inside
        `action_activate` would be the next thing to drift, which is the whole
        defect this method exists to close.
        """
        self.ensure_one()
        is_percent = self.surcharge_type == 'percent'
        return {
            'version_id': self.version_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'calculation_method': 'percent_salary' if is_percent else 'fixed',
            'percent': self.surcharge_percent if is_percent else 0,
            'amount': 0 if is_percent else self.surcharge_amount,
            'notes': f'Job combining: {self.combined_job_id.name}',
        }

    def _sync_allowance(self):
        """Hold the surcharge to what the combination says it is.

        Payroll never reads this model: it reads `version.allowance_ids`, and
        the allowance keeps its own copy of the period, the rate and the
        version. That copy used to be written once at activation and once at
        cancellation, and nothing after. Correcting `date_to` here therefore
        moved the staff unit and left the money alone — the staffing table said
        the post was free from July while the surcharge went on being paid
        through September, and every recomputation of those months paid it
        again. Correcting the percentage moved the figure on this form and
        nothing on the payslip.

        A combination cancelled before it ever started is the one case with no
        period to mirror. Its allowance is closed the day before it opens, so
        `is_active` can never come out true: an empty end date on a start that
        is still ahead would come alive the moment anything rewrote those
        dates, because that flag is stored and recomputed only from them.
        """
        for record in self:
            allowance = record.allowance_id
            if not allowance:
                continue
            values = record._allowance_values()
            if record.state == 'cancelled' and not record.date_to \
                    and record.date_from:
                values['date_to'] = record.date_from - timedelta(days=1)
            allowance.write(values)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            # Find current version with contract
            version = self.employee_id.current_version_id
            if version and version.contract_date_start:
                self.version_id = version.id

    @api.onchange('version_id')
    def _onchange_version_id_reset_combined(self):
        """Reset combined_job/department if they belong to a different company
        than the version (company_id is related to version_id.company_id)."""
        if not self.version_id:
            return
        version_company = self.version_id.company_id
        if self.combined_job_id and self.combined_job_id.company_id \
                and self.combined_job_id.company_id != version_company:
            self.combined_job_id = False
        if self.combined_department_id and self.combined_department_id.company_id \
                and self.combined_department_id.company_id != version_company:
            self.combined_department_id = False

    def action_activate(self):
        """Activate job combining and create allowance"""
        for record in self:
            if record.state != 'draft':
                raise UserError('Only draft job combining can be activated.')

            # Create allowance on version
            combining_type = self.env['hr.allowance.type'].search([
                ('code', '=', 'COMBINING')
            ], limit=1)

            if combining_type:
                allowance = self.env['hr.version.allowance'].create(dict(
                    record._allowance_values(),
                    allowance_type_id=combining_type.id,
                ))
                record.allowance_id = allowance.id

            record.state = 'active'

    def action_cancel(self):
        """Cancel job combining and deactivate allowance.

        The end date is stamped on the combination itself, not only on the
        allowance. Occupancy is dated now, and a cancellation that recorded no
        end date could say nothing about *when* the post was freed — so the
        whole history of the combination dropped out at once, including the
        years it genuinely ran.

        The unit is freed the day after: the surcharge is paid through
        `date_to`, so the post is held through `date_to` too.

        One case has no honest end date — a combination cancelled before it
        ever started. Stamping today would put the end before the start and
        trip `_check_dates`; leaving it empty says what is true, that this
        combination never ran, and the count drops it.

        The surcharge is not closed here but in `_sync_allowance`, which the
        write below reaches. Both dates come from one place, so cancelling and
        correcting the period afterwards cannot disagree.
        """
        for record in self:
            if record.state != 'active':
                raise UserError('Only active job combining can be cancelled.')

            ends_on = record.date_to or fields.Date.context_today(record)
            if record.date_from and ends_on < record.date_from:
                ends_on = False

            # The allowance follows from the write: `date_to` is in the vals,
            # so `_sync_allowance_period` closes it on the same day. One route
            # for the surcharge, whether the date arrives from this button or
            # from an officer correcting the period afterwards.
            record.write({'state': 'cancelled', 'date_to': ends_on})

    def action_draft(self):
        """Reset to draft"""
        for record in self:
            if record.state == 'active':
                raise UserError('Cannot reset an active job combining to draft. Cancel it first.')
            record.state = 'draft'
