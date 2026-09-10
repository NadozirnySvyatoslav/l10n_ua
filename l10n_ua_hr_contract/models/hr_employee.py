from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # UA version fields on the card, in the core pattern: related through
    # `version_id`, the delegation target (`_inherits = {'hr.version':
    # 'version_id'}`), never through `current_version_id`.
    #
    # `version_id` is a compute with `@api.depends_context('version_id')`:
    # the versions timeline widget puts the version being looked at into the
    # context, and the whole card follows it. Pointed at `current_version_id`
    # instead, these fields kept showing today's version while the native
    # ones switched — and an edit made in that state was written to today's
    # version rather than the one on screen.
    #
    # The groups are stated even though a related field already borrows them
    # from its target (`Field._related_groups`), so deleting these declarations
    # would not have opened the fields up. They are written out because core
    # asks for it on every version field carrying a group
    # (`addons/hr/models/hr_employee.py:178`) and because `hr.tests.
    # TestPayrollFieldsAccess.test_related_fields_on_version` reads them off the
    # declaration: a group that only exists by inheritance is a group nobody
    # sees when reading this file. They mirror `hr.version` one for one.
    contract_type_ua = fields.Selection(
        related='version_id.contract_type_ua', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    is_main_workplace = fields.Boolean(
        related='version_id.is_main_workplace', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    is_part_time = fields.Boolean(
        related='version_id.is_part_time', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    part_time_type = fields.Selection(
        related='version_id.part_time_type', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    work_mode = fields.Selection(
        related='version_id.work_mode', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    work_rate = fields.Float(
        related='version_id.work_rate', inherited=True,
        readonly=False, groups="hr.group_hr_user")
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

    # `depends_context` again, for the same reason as on the line itself: a
    # compute inherits nothing from what it depends on, so a field fed by a
    # context-dependent one has to declare the context key of its own accord.
    @api.depends('staffing_line_id')
    @api.depends_context('version_id')
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
    @api.depends_context('version_id')
    def _compute_staffing_line_id(self):
        """Staffing line of this employee's position, as of the version shown.

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

        `depends_context('version_id')` because `date_version`, `job_id`,
        `department_id` and `contract_date_*` are all delegated to the version
        and therefore answer differently under the timeline's context. A
        related field picks that up on its own — `Field.get_depends()` walks
        the path and collects the context keys of every step — but a compute
        gets only what its own decorators declare. Without it the cache key
        is the same in every context, so whichever version was read first in
        the transaction wins and the panel shows, next to the position, the
        line and salary of a version that is not the one on screen.
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
        related='version_id.tariff_grade_id', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    work_conditions = fields.Selection(
        related='version_id.work_conditions', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    work_conditions_class = fields.Integer(
        related='version_id.work_conditions_class', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    work_conditions_subclass = fields.Integer(
        related='version_id.work_conditions_subclass', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    # No `readonly=False` on this one and on probation_end_date: both are
    # stored computes on hr.version. Offering them for editing on the card
    # only invited a value the next recompute would silently drop.
    additional_vacation_days = fields.Integer(
        related='version_id.additional_vacation_days', inherited=True,
        groups="hr.group_hr_user")
    diia_city_employee = fields.Boolean(
        related='version_id.diia_city_employee', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    hire_order_number = fields.Char(
        related='version_id.hire_order_number', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    hire_order_date = fields.Date(
        related='version_id.hire_order_date', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    termination_order_number = fields.Char(
        related='version_id.termination_order_number', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    termination_order_date = fields.Date(
        related='version_id.termination_order_date', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    termination_reason_ua_id = fields.Many2one(
        related='version_id.termination_reason_ua_id', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    probation_period_days = fields.Integer(
        related='version_id.probation_period_days', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    probation_end_date = fields.Date(
        related='version_id.probation_end_date', inherited=True,
        groups="hr.group_hr_user")

    # One2many fields of the version being looked at.
    allowance_ids = fields.One2many(
        related='version_id.allowance_ids', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    salary_change_ids = fields.One2many(
        related='version_id.salary_change_ids', inherited=True,
        readonly=False, groups="hr.group_hr_user")
    amendment_ids = fields.One2many(
        related='version_id.amendment_ids', inherited=True,
        readonly=False, groups="hr.group_hr_user")

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
