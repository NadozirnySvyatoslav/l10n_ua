from odoo import models, fields, api
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import calendar


class HrTimesheet(models.Model):
    _name = 'hr.timesheet'
    _description = 'Timesheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, month desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year,
        tracking=True
    )
    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True, tracking=True)
    
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    
    line_ids = fields.One2many(
        'hr.timesheet.line',
        'timesheet_id',
        string='Timesheet Lines'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', tracking=True)
    
    responsible_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user
    )
    
    total_employees = fields.Integer(
        string='Total Employees',
        compute='_compute_totals',
        store=True
    )
    total_worked_days = fields.Integer(
        string='Total Worked Days',
        compute='_compute_totals',
        store=True
    )
    total_worked_hours = fields.Float(
        string='Total Worked Hours',
        compute='_compute_totals',
        store=True
    )
    
    notes = fields.Text(string='Notes')

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.department_id and self.department_id.company_id \
                and self.department_id.company_id != self.company_id:
            self.department_id = False

    @api.depends('year', 'month', 'department_id')
    def _compute_name(self):
        month_names = dict(self._fields['month'].selection)
        for rec in self:
            dept = rec.department_id.name if rec.department_id else 'All'
            rec.name = f'Табель {month_names.get(rec.month, "")} {rec.year} - {dept}'

    @api.depends('line_ids.worked_days', 'line_ids.worked_hours')
    def _compute_totals(self):
        for rec in self:
            rec.total_employees = len(rec.line_ids)
            rec.total_worked_days = sum(rec.line_ids.mapped('worked_days'))
            rec.total_worked_hours = sum(rec.line_ids.mapped('worked_hours'))

    def action_generate_lines(self):
        """Generate timesheet lines for all employees"""
        self.ensure_one()
        self.line_ids.unlink()
        
        domain = [('company_id', '=', self.company_id.id)]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))

        year, month = self.year, int(self.month)
        month_start = fields.Date.from_string(f'{year}-{month:02d}-01')
        month_end = month_start.replace(day=calendar.monthrange(year, month)[1])

        # Only employees under a contract on some day of the month. Archived
        # ones are included: whoever was dismissed within the month is
        # archived by the order and still has the days worked before it.
        # A card without any contract gets no line at all, rather than a
        # full month of work it never did.
        employees = self.env['hr.employee'].with_context(
            active_test=False).search(domain)._l10n_ua_contracted_between(
            month_start, month_end)

        for employee in employees:
            line = self.env['hr.timesheet.line'].create({
                'timesheet_id': self.id,
                'employee_id': employee.id,
            })
            line.action_generate_days()
        
        return True

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_month_department_id_company_id = models.Constraint(
        'unique(year, month, department_id, company_id)',
        'Timesheet for this period already exists!',
    )


class HrTimesheetLine(models.Model):
    _name = 'hr.timesheet.line'
    _description = 'Timesheet Line'
    _order = 'employee_id'

    timesheet_id = fields.Many2one(
        'hr.timesheet',
        string='Timesheet',
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
        store=True
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True
    )
    
    day_ids = fields.One2many(
        'hr.timesheet.day',
        'line_id',
        string='Days'
    )
    
    scheduled_days = fields.Integer(
        string='Scheduled Days',
        compute='_compute_totals',
        store=True
    )
    worked_days = fields.Integer(
        string='Worked Days',
        compute='_compute_totals',
        store=True
    )
    worked_hours = fields.Float(
        string='Worked Hours',
        compute='_compute_totals',
        store=True
    )
    overtime_hours = fields.Float(
        string='Overtime Hours',
        compute='_compute_totals',
        store=True
    )
    night_hours = fields.Float(
        string='Night Hours',
        compute='_compute_totals',
        store=True
    )
    holiday_hours = fields.Float(
        string='Holiday Hours',
        compute='_compute_totals',
        store=True,
        help='Години роботи у святкові/неробочі дні (для доплати ×2).'
    )
    absence_days = fields.Integer(
        string='Absence Days',
        compute='_compute_totals',
        store=True
    )
    vacation_days = fields.Integer(
        string='Vacation Days',
        compute='_compute_totals',
        store=True
    )
    sick_days = fields.Integer(
        string='Sick Days',
        compute='_compute_totals',
        store=True
    )

    @api.depends('day_ids.code_id', 'day_ids.hours', 'day_ids.overtime_hours', 'day_ids.night_hours')
    def _compute_totals(self):
        for line in self:
            days = line.day_ids
            # The norm of the month: its working days by the production
            # calendar (see action_generate_days), not the days worked.
            line.scheduled_days = len(days.filtered('is_scheduled'))
            line.worked_days = len(days.filtered(lambda d: d.code_id.is_worked))
            line.worked_hours = sum(days.mapped('hours'))
            line.overtime_hours = sum(days.mapped('overtime_hours'))
            line.night_hours = sum(days.mapped('night_hours'))
            line.holiday_hours = sum(
                days.filtered(lambda d: d.code_id.code_type == 'holiday').mapped('hours'))
            line.absence_days = len(days.filtered(lambda d: d.code_id.code_type == 'absence'))
            line.vacation_days = len(days.filtered(lambda d: d.code_id.code_type == 'leave'))
            line.sick_days = len(days.filtered(lambda d: d.code_id.code_type == 'sick'))

    def action_generate_days(self):
        """Generate day entries for the month"""
        self.ensure_one()
        self.day_ids.unlink()

        year = self.timesheet_id.year
        month = int(self.timesheet_id.month)

        _, last_day = calendar.monthrange(year, month)

        # Get codes
        work_code = self.env['hr.timesheet.code'].search([('code', '=', 'Я')], limit=1)
        weekend_code = self.env['hr.timesheet.code'].search([('code', '=', 'В')], limit=1)
        holiday_code = self.env['hr.timesheet.code'].search([('code', '=', 'СВ')], limit=1)
        vacation_code = self.env['hr.timesheet.code'].search([('code', '=', 'ВД')], limit=1)
        sick_code = self.env['hr.timesheet.code'].search([('code', '=', 'ТН')], limit=1)
        # Code for days before contract start or after contract end
        not_employed_code = self.env['hr.timesheet.code'].search([('code', '=', 'НР')], limit=1)
        if not not_employed_code:
            not_employed_code = self.env['hr.timesheet.code'].search([('code', '=', 'ІН')], limit=1)

        employee = self.employee_id
        version = employee.current_version_id
        # `work_rate` додає l10n_ua_hr_contract, якого цей модуль не вимагає.
        work_rate = (version.work_rate
                     if version and 'work_rate' in version._fields else 1.0)

        # Calculate standard hours based on work_rate
        standard_hours = 8.0 * work_rate

        # Get production calendar
        prod_calendar = self.env['hr.production.calendar'].search([
            ('year', '=', year),
            ('company_id', '=', self.timesheet_id.company_id.id),
        ], limit=1)

        # Get employee leaves for the month
        date_from = fields.Date.from_string(f'{year}-{month:02d}-01')
        date_to = fields.Date.from_string(f'{year}-{month:02d}-{last_day}')

        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ])

        sick_leaves = self.env['hr.sick.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['confirmed', 'paid']),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ])

        days = []
        for day in range(1, last_day + 1):
            date = fields.Date.from_string(f'{year}-{month:02d}-{day:02d}')

            # Check production calendar
            cal_line = prod_calendar.line_ids.filtered(lambda l: l.date == date) if prod_calendar else False

            # `is_scheduled` is the month's norm: a working day of the
            # production calendar (Monday to Friday without one), whatever
            # the employee did on it. Vacation, sick leave and days outside
            # the contract stay in the norm and only miss from the worked
            # days, so the payslip pays the part of the month actually
            # worked. Excluding them made worked == scheduled, a full salary.
            if cal_line:
                is_scheduled = cal_line.day_type not in ('holiday', 'weekend')
            else:
                is_scheduled = date.weekday() < 5

            # Determine code and hours
            code = work_code
            hours = standard_hours

            if not employee._l10n_ua_employed_on(date):
                # Employee not yet hired or already terminated
                code = not_employed_code or weekend_code
                hours = 0
            else:
                # Check if it's a leave day
                leave_day = leaves.filtered(
                    lambda l: l.date_from.date() <= date <= l.date_to.date()
                )
                sick_day = sick_leaves.filtered(
                    lambda s: s.date_from <= date <= s.date_to
                )

                if sick_day:
                    code = sick_code
                    hours = 0
                elif leave_day:
                    code = vacation_code
                    hours = 0
                elif cal_line:
                    if cal_line.day_type == 'holiday':
                        code = holiday_code
                        hours = 0
                    elif cal_line.day_type == 'weekend':
                        code = weekend_code
                        hours = 0
                    else:
                        # Apply work_rate to calendar hours
                        hours = cal_line.working_hours * work_rate
                elif date.weekday() >= 5:
                    code = weekend_code
                    hours = 0

            days.append({
                'line_id': self.id,
                'date': date,
                'day_number': day,
                'code_id': code.id if code else False,
                'hours': hours,
                'is_scheduled': is_scheduled,
            })

        self.env['hr.timesheet.day'].create(days)
        return True


class HrTimesheetDay(models.Model):
    _name = 'hr.timesheet.day'
    _description = 'Timesheet Day'
    _order = 'day_number'

    line_id = fields.Many2one(
        'hr.timesheet.line',
        string='Timesheet Line',
        required=True,
        ondelete='cascade'
    )
    date = fields.Date(string='Date', required=True)
    day_number = fields.Integer(string='Day')
    
    code_id = fields.Many2one(
        'hr.timesheet.code',
        string='Code',
        required=True
    )
    hours = fields.Float(string='Hours', default=0)
    overtime_hours = fields.Float(string='Overtime')
    night_hours = fields.Float(string='Night Hours')
    
    is_scheduled = fields.Boolean(string='Scheduled')
    notes = fields.Char(string='Notes')
