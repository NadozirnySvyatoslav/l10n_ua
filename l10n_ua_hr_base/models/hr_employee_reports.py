from datetime import date

from odoo import models, fields, api


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
            rec.employee_count = len(rec.employee_ids)

    def _domain_employees(self):
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ]

    def action_generate(self):
        for rec in self:
            employees = rec.env['hr.employee'].search(rec._domain_employees())
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
            rec.employee_count = len(rec.employee_ids)
            rec.reserved_count = len(rec.employee_ids.filtered('military_reservation'))

    def action_generate(self):
        for rec in self:
            employees = rec.env['hr.employee'].search([
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                ('military_register_category', 'in',
                    ['conscript', 'liable', 'reservist']),
            ])
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


class HrEmployeeMilitaryOperationalReport(models.Model):
    """Відомість оперативного військового обліку — журнал змін за період (ПКМУ № 1487).

    Tracks military-related events during a date range: hires, dismissals,
    register_category changes, reservation changes. Source data comes from
    mail.message tracking values on hr.employee (military_* fields are tracked
    automatically by Odoo's mail.thread when @tracking is set on the model).
    """
    _name = 'hr.employee.military.operational.report'
    _description = 'Військовий облік: відомість оперативного обліку'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    date_from = fields.Date(
        string='Період з',
        required=True,
        default=lambda self: date.today().replace(day=1),
        tracking=True,
    )
    date_to = fields.Date(
        string='Період до',
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
    line_ids = fields.One2many(
        'hr.employee.military.operational.report.line',
        'report_id',
        string='Записи журналу',
    )
    line_count = fields.Integer(
        compute='_compute_line_count', store=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('generated', 'Generated')],
        default='draft',
        tracking=True,
    )

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.name = (
                    f"Оперативний облік {rec.date_from.strftime('%d.%m.%Y')} – "
                    f"{rec.date_to.strftime('%d.%m.%Y')}"
                )
            else:
                rec.name = "Оперативний військовий облік"

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_generate(self):
        """Build journal from hr.order events + employee tracking changes."""
        self.ensure_one()
        self.line_ids.unlink()
        lines = []
        Order = self.env.get('hr.order')

        # 1) Hires + dismissals from hr.order (if l10n_ua_hr_documents installed)
        if Order is not None:
            orders = Order.search([
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('order_type', 'in', ['hiring', 'dismissal']),
                ('company_id', '=', self.company_id.id),
                ('state', '!=', 'cancelled'),
            ])
            for order in orders:
                if not order.employee_id or order.employee_id.military_register_category == 'not_applicable':
                    continue
                event = 'Прийом на роботу' if order.order_type == 'hiring' else 'Звільнення'
                lines.append((0, 0, {
                    'date': order.date,
                    'employee_id': order.employee_id.id,
                    'event_type': order.order_type,
                    'description': f'{event} (наказ № {order.name})',
                }))

        # 2) Tracked field changes from mail.message
        domain = [
            ('model', '=', 'hr.employee'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        messages = self.env['mail.message'].search(domain)
        tracked_fields = (
            'military_register_category', 'military_fitness',
            'military_reservation', 'military_reservation_until',
            'military_medical_category',
        )
        for msg in messages:
            for tracking in msg.tracking_value_ids:
                if tracking.field_id.name not in tracked_fields:
                    continue
                employee = self.env['hr.employee'].browse(msg.res_id)
                if not employee.exists() or employee.company_id != self.company_id:
                    continue
                lines.append((0, 0, {
                    'date': msg.date.date(),
                    'employee_id': employee.id,
                    'event_type': 'change',
                    'description': (
                        f'{tracking.field_id.field_description}: '
                        f'{tracking.old_value_char or tracking.old_value_text or "—"} → '
                        f'{tracking.new_value_char or tracking.new_value_text or "—"}'
                    ),
                }))

        self.write({
            'line_ids': lines,
            'state': 'generated',
        })
        return True

    def action_draft(self):
        self.line_ids.unlink()
        self.write({'state': 'draft'})


class HrEmployeeMilitaryOperationalReportLine(models.Model):
    _name = 'hr.employee.military.operational.report.line'
    _description = 'Запис журналу оперативного обліку'
    _order = 'date, id'

    report_id = fields.Many2one(
        'hr.employee.military.operational.report',
        required=True, ondelete='cascade', index=True,
    )
    date = fields.Date(required=True)
    employee_id = fields.Many2one('hr.employee', required=True)
    event_type = fields.Selection([
        ('hiring', 'Прийом на роботу'),
        ('dismissal', 'Звільнення'),
        ('change', 'Зміна стану'),
    ], required=True)
    description = fields.Char()


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
            employees = rec.employee_ids
            rec.employee_count = len(employees)
            rec.disabled_count = len(employees.filtered(
                lambda e: e.disability_group and e.disability_group != 'none'))
            rec.chornobyl_count = len(employees.filtered(
                lambda e: e.chornobyl_category and e.chornobyl_category != 'none'))
            rec.veteran_count = len(employees.filtered(
                lambda e: e.veteran_status and e.veteran_status != 'none'))

    def action_generate(self):
        for rec in self:
            employees = rec.env['hr.employee'].search([
                ('company_id', '=', rec.company_id.id),
                ('active', '=', True),
                '|', '|', '|',
                ('disability_group', 'not in', [False, 'none']),
                ('chornobyl_category', 'not in', [False, 'none']),
                ('veteran_status', 'not in', [False, 'none']),
                ('benefit_ids', '!=', False),
            ])
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
