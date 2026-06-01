from odoo import models, fields, api

def _was_employed_on(employee, as_of):
    """Return True if employee (active or archived) was employed on as_of date.

    Applied to every candidate so the report lists only people whose
    contract covered the report date.
    """
    if not as_of:
        return True
    versions = employee.version_ids.filtered('contract_date_start')
    if versions:
        return any(
            v.contract_date_start <= as_of
            and (not v.contract_date_end or v.contract_date_end >= as_of)
            for v in versions
        )
    # Fallback when no contract version is available yet.
    return bool(employee.hire_date) and employee.hire_date <= as_of

class HrEmployeeListReport(models.Model):
    """Employee List Report (Список працівників).

    Snapshot of active employees as of a specific date. Saved and
    reusable; can be regenerated and printed to PDF.
    """
    _name = 'hr.employee.list.report'
    _description = 'Employee List Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Список працівників станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = 'Список працівників'

    @api.depends('employee_ids')
    def _compute_employee_count(self):
        for rec in self:
            rec.employee_count = len(rec.with_context(active_test=False).employee_ids)

    def _domain_employees(self):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
        ]

    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(
                active_test=False).search(rec._domain_employees())
            as_of = rec.date
            # Keep only employees (active or archived) employed on the date.
            employees = candidates.filtered(
                lambda e: _was_employed_on(e, as_of))

            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_list'
        ).report_action(self)


class HrEmployeeMilitaryReport(models.Model):
    """Military Personnel Report (Військовозобов'язані)."""
    _name = 'hr.employee.military.report'
    _description = 'Military Personnel Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    reserved_count = fields.Integer(
        string='Reserved',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Військовозобов'язані станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = "Військовозобов'язані"

    @api.depends('employee_ids', 'employee_ids.military_reservation')
    def _compute_employee_count(self):
        for rec in self:
            employees = rec.with_context(active_test=False).employee_ids
            rec.employee_count = len(employees)
            rec.reserved_count = len(employees.filtered('military_reservation'))


    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(active_test=False).search([
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                ('military_status', 'in', ['liable', 'reserved']),
            ])
            as_of = rec.date
            employees = candidates.filtered(
                lambda e: _was_employed_on(e, as_of))
            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_military'
        ).report_action(self)


class HrEmployeeBenefitsReport(models.Model):
    """Employees with Benefits Report (Працівники з пільгами)."""
    _name = 'hr.employee.benefits.report'
    _description = 'Employees with Benefits Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='As of Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    employee_count = fields.Integer(
        string='Total',
        compute='_compute_employee_count',
        store=True,
    )
    disabled_count = fields.Integer(
        string='With Disability',
        compute='_compute_employee_count',
        store=True,
    )
    chornobyl_count = fields.Integer(
        string='Chornobyl',
        compute='_compute_employee_count',
        store=True,
    )
    veteran_count = fields.Integer(
        string='Veterans',
        compute='_compute_employee_count',
        store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )
    notes = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            if rec.date:
                rec.name = f"Працівники з пільгами станом на {rec.date.strftime('%d.%m.%Y')}"
            else:
                rec.name = 'Працівники з пільгами'

    @api.depends('employee_ids', 'employee_ids.disability_group',
                 'employee_ids.chornobyl_category', 'employee_ids.veteran_status')
    def _compute_employee_count(self):
        for rec in self:
            employees = rec.with_context(active_test=False).employee_ids
            rec.employee_count = len(employees)
            rec.disabled_count = len(employees.filtered(
                lambda e: e.disability_group and e.disability_group != 'none'))
            rec.chornobyl_count = len(employees.filtered(
                lambda e: e.chornobyl_category and e.chornobyl_category != 'none'))
            rec.veteran_count = len(employees.filtered(
                lambda e: e.veteran_status and e.veteran_status != 'none'))

    def action_generate(self):
        for rec in self:
            candidates = rec.env['hr.employee'].with_context(active_test=False).search([
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                '|', '|', '|',
                ('disability_group', 'not in', [False, 'none']),
                ('chornobyl_category', 'not in', [False, 'none']),
                ('veteran_status', 'not in', [False, 'none']),
                ('benefit_ids', '!=', False),
            ])
            as_of = rec.date
            employees = candidates.filtered(
                lambda e: _was_employed_on(e, as_of))
            rec.write({
                'employee_ids': [(6, 0, employees.ids)],
                'state': 'generated',
            })
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_hr_base.action_report_hr_employee_benefits'
        ).report_action(self)
