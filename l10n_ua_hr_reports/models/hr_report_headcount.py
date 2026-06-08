from odoo import models, fields, api
from calendar import monthrange
from datetime import date, timedelta


class HrReportHeadcount(models.Model):
    """Average Headcount Report (Середньооблікова чисельність)

    Calculates average headcount according to Ukrainian methodology
    (Order of State Statistics Committee #286, 28.09.2005).
    """
    _name = 'hr.report.headcount'
    _description = 'Average Headcount Report'
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

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # Report results
    avg_headcount = fields.Float(
        string='Average Headcount (Full-time)',
        digits=(10, 2),
        help='Average headcount of full-time employees'
    )
    avg_headcount_full = fields.Float(
        string='Average Headcount (All)',
        digits=(10, 2),
        help='Average headcount including part-time (FTE equivalent)'
    )

    total_calendar_days = fields.Integer(
        string='Calendar Days',
        help='Total calendar days in the period'
    )

    line_ids = fields.One2many(
        'hr.report.headcount.line',
        'report_id',
        string='Daily Data'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Notes')

    @api.depends('year', 'month')
    def _compute_name(self):
        month_names = {
            '1': 'Січень', '2': 'Лютий', '3': 'Березень',
            '4': 'Квітень', '5': 'Травень', '6': 'Червень',
            '7': 'Липень', '8': 'Серпень', '9': 'Вересень',
            '10': 'Жовтень', '11': 'Листопад', '12': 'Грудень',
        }
        for rec in self:
            month_name = month_names.get(rec.month, rec.month)
            rec.name = f'Середньооблікова чисельність {month_name} {rec.year}'

    def action_generate(self):
        """Generate daily headcount data and calculate average"""
        self.ensure_one()
        self.line_ids.unlink()

        month_int = int(self.month)
        days_in_month = monthrange(self.year, month_int)[1]

        total_headcount = 0
        total_fte = 0

        for day in range(1, days_in_month + 1):
            current_date = date(self.year, month_int, day)

            # Count employees who were employed on this date
            headcount, fte = self._count_employees_on_date(current_date)

            self.env['hr.report.headcount.line'].create({
                'report_id': self.id,
                'date': current_date,
                'headcount': headcount,
                'fte_count': fte,
            })

            total_headcount += headcount
            total_fte += fte

        # Calculate average
        self.write({
            'avg_headcount': round(total_headcount / days_in_month, 2),
            'avg_headcount_full': round(total_fte / days_in_month, 2),
            'total_calendar_days': days_in_month,
            'state': 'generated',
        })

        return True

    def _count_employees_on_date(self, check_date):
        """Count employees on a specific date.

        Returns tuple (headcount, fte):
        - headcount: number of full-time employees
        - fte: full-time equivalent (includes part-time workers proportionally)
        """
        headcount = 0
        fte = 0.0

        # Find all employees with active contracts on this date
        # Using hr.version to check employment period
        versions = self.env['hr.version'].with_context(active_test=False).search([
            ('employee_id.company_id', '=', self.company_id.id),
            ('contract_date_start', '<=', check_date),
            '|',
            ('contract_date_end', '=', False),
            ('contract_date_end', '>', check_date),
        ])

        for version in versions:
            # Get work rate (e.g., 1.0 for full-time, 0.5 for half-time)
            work_rate = 1.0
            if hasattr(version, 'work_rate') and version.work_rate:
                work_rate = version.work_rate
            elif hasattr(version, 'staffing_line_id') and version.staffing_line_id:
                # Try to get from staffing table
                staffing = version.staffing_line_id
                if hasattr(staffing, 'units') and staffing.units:
                    work_rate = staffing.units

            if work_rate >= 1.0:
                headcount += 1
            fte += work_rate

        return headcount, fte

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_month_company_id = models.Constraint(
        'unique(year, month, company_id)',
        'Headcount report for this period already exists!',
    )


class HrReportHeadcountLine(models.Model):
    _name = 'hr.report.headcount.line'
    _description = 'Headcount Report Daily Line'
    _order = 'date'

    report_id = fields.Many2one(
        'hr.report.headcount',
        string='Report',
        required=True,
        ondelete='cascade'
    )
    date = fields.Date(string='Date', required=True)
    day_of_week = fields.Char(
        string='Day',
        compute='_compute_day_of_week'
    )
    headcount = fields.Integer(
        string='Headcount',
        help='Number of full-time employees'
    )
    fte_count = fields.Float(
        string='FTE',
        digits=(10, 2),
        help='Full-time equivalent count'
    )

    @api.depends('date')
    def _compute_day_of_week(self):
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']
        for rec in self:
            if rec.date:
                rec.day_of_week = days[rec.date.weekday()]
            else:
                rec.day_of_week = ''
