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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.job.combining') or 'New'
        return super().create(vals_list)

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

    def _recompute_staffing(self):
        """Have the staffing table count the combined positions again.

        `filled_units` has no `@api.depends` path to a combination, so a
        change of state has to be reported here by hand.

        Through `add_to_compute`, not by calling the compute directly. The
        direct call runs under the rights of whoever is writing and stores
        what it produces, and the count reads `contract_date_*`, which core
        keeps behind hr.group_hr_manager: an officer without that group would
        get an AccessError where everything used to work quietly. Going
        through the ORM gets the field the `compute_sudo` it is entitled to.
        """
        Staffing = self.env.get('hr.staffing.table')
        if Staffing is None:
            return
        Staffing._recompute_occupancy({
            (record.company_id.id, record.combined_department_id.id,
             record.combined_job_id.id)
            for record in self
        })

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
                allowance_vals = {
                    'version_id': record.version_id.id,
                    'allowance_type_id': combining_type.id,
                    'calculation_method': 'percent_salary' if record.surcharge_type == 'percent' else 'fixed',
                    'percent': record.surcharge_percent if record.surcharge_type == 'percent' else 0,
                    'amount': record.surcharge_amount if record.surcharge_type == 'fixed' else 0,
                    'date_from': record.date_from,
                    'date_to': record.date_to,
                    'notes': f'Job combining: {record.combined_job_id.name}',
                }
                allowance = self.env['hr.version.allowance'].create(allowance_vals)
                record.allowance_id = allowance.id

            record.state = 'active'
            record._recompute_staffing()

    def action_cancel(self):
        """Cancel job combining and deactivate allowance"""
        for record in self:
            if record.state != 'active':
                raise UserError('Only active job combining can be cancelled.')

            # Deactivate related allowance by setting end date
            if record.allowance_id:
                record.allowance_id.date_to = fields.Date.today()

            record.state = 'cancelled'
            record._recompute_staffing()

    def action_draft(self):
        """Reset to draft"""
        for record in self:
            if record.state == 'active':
                raise UserError('Cannot reset an active job combining to draft. Cancel it first.')
            record.state = 'draft'
