from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrVacationSchedule(models.Model):
    _name = 'hr.vacation.schedule'
    _description = 'Vacation Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year + 1,
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    
    line_ids = fields.One2many(
        'hr.vacation.schedule.line',
        'schedule_id',
        string='Schedule Lines'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', tracking=True)
    
    approval_date = fields.Date(string='Approval Date')
    approved_by = fields.Many2one('res.users', string='Approved By')
    
    notes = fields.Text(string='Notes')

    @api.depends('year', 'company_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f'Графік відпусток {rec.year} - {rec.company_id.name}'

    def action_generate_lines(self):
        """Generate schedule lines for all employees"""
        self.ensure_one()
        self.line_ids.unlink()
        
        domain = [('company_id', '=', self.company_id.id)]
        if 'contract_id' in self.env['hr.employee']._fields:
            domain.append(('contract_id.state', '=', 'open'))
        
        employees = self.env['hr.employee'].search(domain)
        
        annual_leave = self.env['hr.leave.type'].search([
            ('ua_leave_category', '=', 'annual_basic'),
        ], limit=1)
        
        for employee in employees:
            balance = self.env['hr.vacation.balance'].search([
                ('employee_id', '=', employee.id),
                ('year', '=', self.year),
            ], limit=1)
            
            days = balance.total_available if balance else (annual_leave.annual_days if annual_leave else 24)
            
            self.env['hr.vacation.schedule.line'].create({
                'schedule_id': self.id,
                'employee_id': employee.id,
                'department_id': employee.department_id.id,
                'planned_days': days,
            })
        
        return True

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_approve(self):
        self.write({
            'state': 'approved',
            'approval_date': fields.Date.today(),
            'approved_by': self.env.uid,
        })

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_company_id = models.Constraint(
        'unique(year, company_id)',
        'Vacation schedule for this year and company already exists!',
    )


class HrVacationScheduleLine(models.Model):
    _name = 'hr.vacation.schedule.line'
    _description = 'Vacation Schedule Line'
    _order = 'department_id, employee_id'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    schedule_id = fields.Many2one(
        'hr.vacation.schedule',
        string='Schedule',
        required=True,
        ondelete='cascade'
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=False
    )
    
    planned_days = fields.Integer(string='Planned Days')
    
    period_1_start = fields.Date(string='Period 1 Start')
    period_1_end = fields.Date(string='Period 1 End')
    period_1_days = fields.Integer(
        string='Period 1 Days',
        compute='_compute_period_days',
        store=True
    )
    
    period_2_start = fields.Date(string='Period 2 Start')
    period_2_end = fields.Date(string='Period 2 End')
    period_2_days = fields.Integer(
        string='Period 2 Days',
        compute='_compute_period_days',
        store=True
    )
    
    period_3_start = fields.Date(string='Period 3 Start')
    period_3_end = fields.Date(string='Period 3 End')
    period_3_days = fields.Integer(
        string='Period 3 Days',
        compute='_compute_period_days',
        store=True
    )
    
    total_planned = fields.Integer(
        string='Total Planned',
        compute='_compute_period_days',
        store=True
    )
    
    actual_days = fields.Integer(
        string='Actual Days',
        compute='_compute_actual_days',
        store=True
    )
    
    notes = fields.Char(string='Notes')

    @api.depends('employee_id', 'department_id', 'period_1_days')
    def _compute_display_name(self):
        for line in self:
            if line.employee_id:
                line.display_name = f"{line.employee_id.name} ({line.period_1_days} дн.)"
            else:
                line.display_name = "Новий запис"

    @api.depends('period_1_start', 'period_1_end', 'period_2_start', 'period_2_end',
                 'period_3_start', 'period_3_end')
    def _compute_period_days(self):
        for line in self:
            days1 = days2 = days3 = 0
            
            if line.period_1_start and line.period_1_end:
                days1 = (line.period_1_end - line.period_1_start).days + 1
            if line.period_2_start and line.period_2_end:
                days2 = (line.period_2_end - line.period_2_start).days + 1
            if line.period_3_start and line.period_3_end:
                days3 = (line.period_3_end - line.period_3_start).days + 1
            
            line.period_1_days = days1
            line.period_2_days = days2
            line.period_3_days = days3
            line.total_planned = days1 + days2 + days3

    @api.depends('employee_id', 'schedule_id.year')
    def _compute_actual_days(self):
        for line in self:
            if not line.employee_id or not line.schedule_id.year:
                line.actual_days = 0
                continue
            year = line.schedule_id.year
            year_start = fields.Date.from_string(f'{year}-01-01')
            year_end   = fields.Date.from_string(f'{year}-12-31')
            leaves = self.env['hr.leave'].search([
                ('employee_id', '=', line.employee_id.id),
                ('state', '=', 'validate'),
                ('holiday_status_id.ua_leave_category', 'in',
                    ['annual_basic', 'annual_additional']),
                '|',
                    ('vacation_year', '=', year),
                    '&', '&',
                        ('vacation_year', 'in', [False, 0]),
                        ('request_date_from', '<=', year_end),
                        ('request_date_to', '>=', year_start),
            ])
            line.actual_days = sum(leaves.mapped('number_of_days'))

    @api.constrains('period_1_start', 'period_1_end', 'period_2_start', 'period_2_end',
                    'period_3_start', 'period_3_end')
    def _check_periods(self):
        for line in self:
            if line.period_1_start and line.period_1_end and line.period_1_start > line.period_1_end:
                raise ValidationError('Period 1: Start date must be before end date.')
            if line.period_2_start and line.period_2_end and line.period_2_start > line.period_2_end:
                raise ValidationError('Period 2: Start date must be before end date.')
            if line.period_3_start and line.period_3_end and line.period_3_start > line.period_3_end:
                raise ValidationError('Period 3: Start date must be before end date.')
