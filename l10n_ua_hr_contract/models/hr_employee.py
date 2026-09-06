from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Related fields from current_version_id for form display
    contract_type_ua = fields.Selection(
        related='current_version_id.contract_type_ua',
        readonly=False
    )
    is_main_workplace = fields.Boolean(
        related='current_version_id.is_main_workplace',
        readonly=False
    )
    is_part_time = fields.Boolean(
        related='current_version_id.is_part_time',
        readonly=False
    )
    part_time_type = fields.Selection(
        related='current_version_id.part_time_type',
        readonly=False
    )
    work_mode = fields.Selection(
        related='current_version_id.work_mode',
        readonly=False
    )
    work_rate = fields.Float(
        related='current_version_id.work_rate',
        readonly=False
    )
    # Derived from department_id + job_id, so no longer writable from the card:
    # the position is entered once, in the native "Job Position" field.
    #
    # Resolved here rather than read from `current_version_id.staffing_line_id`:
    # that field is a stored compute over `version_ids.date_version`, so a
    # department or job picked in an unsaved form never reaches it and the panel
    # stayed empty until the record was saved. The fields the form actually
    # edits are on the card itself, so the panel now follows them at once. The
    # date rule is the shared one, so the card and the version cannot disagree.
    staffing_line_id = fields.Many2one(
        'hr.staffing.table',
        string='Staffing Position',
        compute='_compute_staffing_line_id',
        groups="hr.group_hr_user",
        help='Staffing table line matching the department and the job of this '
             'employee. Not filled in by hand: the position is entered once, '
             'in the native Job Position field, and the staffing line follows '
             'from it.'
    )
    # Details of that line, shown next to the position on the Work tab.
    #
    # Read through one compute rather than declared as `related=` on the line.
    # A related field depends on a two-step path, and the ORM warns that the
    # first step is not searchable: it cannot tell which cards to recompute
    # when a staffing line changes. Depending on the field of this same record
    # is a single step and asks the ORM nothing it cannot answer.
    #
    # The labels are stated here for the same reason. A related field borrows
    # the string of the field it points at, so these arrived on the card as
    # "Salary" and "Currency" — a collision with the employee's own currency
    # that Odoo reports on every upgrade, and worse, a promise that this is the
    # person's salary when it is the position's.
    #
    # The group is stated on every one of them too. Salary is not something to
    # leave guarded by the coincidence that hr.employee happens to be HR-only.
    staffing_line_start = fields.Date(
        string='Staffing Line Start', compute='_compute_staffing_details',
        groups="hr.group_hr_user")
    staffing_state = fields.Selection(
        # The translated list, not the raw one: a callable selection gets no
        # `ir.model.fields.selection` records of its own, so it cannot be
        # translated through the .po. Borrowing the source field's own
        # labels keeps the card in step with the staffing table — in every
        # language, and through any state it may gain later.
        selection=lambda self: self.env['hr.staffing.table']._fields[
            'state']._description_selection(self.env),
        string='Staffing Line Status', compute='_compute_staffing_details',
        groups="hr.group_hr_user")
    staffing_currency_id = fields.Many2one(
        'res.currency', string='Staffing Currency',
        compute='_compute_staffing_details', groups="hr.group_hr_user")
    staffing_salary = fields.Monetary(
        string='Staffing Salary', compute='_compute_staffing_details',
        currency_field='staffing_currency_id', groups="hr.group_hr_user")
    staffing_salary_min = fields.Monetary(
        string='Staffing Minimum Salary', compute='_compute_staffing_details',
        currency_field='staffing_currency_id', groups="hr.group_hr_user")
    staffing_salary_max = fields.Monetary(
        string='Staffing Maximum Salary', compute='_compute_staffing_details',
        currency_field='staffing_currency_id', groups="hr.group_hr_user")

    @api.depends('staffing_line_id')
    def _compute_staffing_details(self):
        for employee in self:
            line = employee.staffing_line_id
            employee.staffing_line_start = line.date_from
            employee.staffing_state = line.state
            employee.staffing_currency_id = line.currency_id
            employee.staffing_salary = line.salary
            employee.staffing_salary_min = line.salary_min
            employee.staffing_salary_max = line.salary_max

    @api.depends('company_id', 'department_id', 'job_id', 'date_version',
                 'contract_date_start', 'contract_date_end',
                 'version_ids.date_version')
    def _compute_staffing_line_id(self):
        """Staffing line of this employee's position, as of today.

        Deliberately not `compute_sudo`. The reference date needs
        `contract_date_start` / `contract_date_end`, which core restricts to
        hr.group_hr_manager, and an HR officer who may not read them still
        needs the panel — so exactly those two reads are elevated, and nothing
        else. The resolution runs under the user: its record rules apply, and a
        line they may not see is simply not found, because a search returns
        fewer rows rather than raising.

        That buys a property a blanket sudo cannot: whatever the resolution
        returns, the reader is entitled to read. The fields fed from it can
        then be read plainly, with no risk of an access error on a form.
        """
        today = fields.Date.context_today(self)
        Staffing = self.env['hr.staffing.table']
        contract_dates = {
            employee.id: (employee.contract_date_start,
                          employee.contract_date_end)
            for employee in self.sudo()
        }
        keys = {}
        for employee in self:
            contract_start, contract_end = contract_dates[employee.id]
            ref_date = Staffing._reference_date(
                employee.date_version, contract_start, contract_end,
                employee.version_ids.mapped('date_version'), today)
            keys[employee.id] = (
                employee.company_id.id, employee.department_id.id,
                employee.job_id.id, ref_date,
            )
        resolved = Staffing._resolve_batch(list(keys.values()))
        for employee in self:
            employee.staffing_line_id = resolved.get(keys[employee.id], False)
    tariff_grade_id = fields.Many2one(
        related='current_version_id.tariff_grade_id',
        readonly=False
    )
    work_conditions = fields.Selection(
        related='current_version_id.work_conditions',
        readonly=False
    )
    work_conditions_class = fields.Integer(
        related='current_version_id.work_conditions_class',
        readonly=False
    )
    work_conditions_subclass = fields.Integer(
        related='current_version_id.work_conditions_subclass',
        readonly=False
    )
    additional_vacation_days = fields.Integer(
        related='current_version_id.additional_vacation_days',
        readonly=False
    )
    diia_city_employee = fields.Boolean(
        related='current_version_id.diia_city_employee',
        readonly=False
    )
    hire_order_number = fields.Char(
        related='current_version_id.hire_order_number',
        readonly=False
    )
    hire_order_date = fields.Date(
        related='current_version_id.hire_order_date',
        readonly=False
    )
    termination_order_number = fields.Char(
        related='current_version_id.termination_order_number',
        readonly=False
    )
    termination_order_date = fields.Date(
        related='current_version_id.termination_order_date',
        readonly=False
    )
    termination_reason_ua_id = fields.Many2one(
        related='current_version_id.termination_reason_ua_id',
        readonly=False
    )
    probation_period_days = fields.Integer(
        related='current_version_id.probation_period_days',
        readonly=False
    )
    probation_end_date = fields.Date(
        related='current_version_id.probation_end_date',
        readonly=False
    )

    # One2many fields through current version
    allowance_ids = fields.One2many(
        related='current_version_id.allowance_ids',
        readonly=False
    )
    salary_change_ids = fields.One2many(
        related='current_version_id.salary_change_ids',
        readonly=False
    )
    amendment_ids = fields.One2many(
        related='current_version_id.amendment_ids',
        readonly=False
    )

    job_combining_ids = fields.One2many(
        'hr.job.combining',
        'employee_id',
        string='Job Combining',
        groups="hr.group_hr_user"
    )
    job_combining_count = fields.Integer(
        string='Job Combining Count',
        compute='_compute_job_combining_count',
        groups="hr.group_hr_user"
    )

    def _compute_job_combining_count(self):
        for employee in self:
            employee.job_combining_count = len(employee.job_combining_ids)

    def action_open_job_combining(self):
        self.ensure_one()
        return {
            'name': 'Job Combining',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.job.combining',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
