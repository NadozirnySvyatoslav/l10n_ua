from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError


class HrReport1DF(models.Model):
    _name = 'hr.report.1df'
    _description = '1DF Tax Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, quarter desc'

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
    quarter = fields.Selection([
        ('1', 'Q1'),
        ('2', 'Q2'),
        ('3', 'Q3'),
        ('4', 'Q4'),
    ], string='Quarter', required=True, tracking=True)
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    
    line_ids = fields.One2many(
        'hr.report.1df.line',
        'report_id',
        string='Report Lines'
    )
    
    total_employees = fields.Integer(
        string='Total Employees',
        compute='_compute_totals',
        store=True
    )
    total_accrued = fields.Float(
        string='Total Accrued',
        compute='_compute_totals',
        store=True
    )
    total_paid = fields.Float(
        string='Total Paid',
        compute='_compute_totals',
        store=True
    )
    total_pdfo = fields.Float(
        string='Total PDFO',
        compute='_compute_totals',
        store=True
    )
    total_military = fields.Float(
        string='Total Military Tax',
        compute='_compute_totals',
        store=True
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('submitted', 'Submitted'),
    ], string='Status', default='draft', tracking=True)
    
    submission_date = fields.Date(string='Submission Date')
    notes = fields.Text(string='Notes')

    @api.depends('year', 'quarter')
    def _compute_name(self):
        for rec in self:
            rec.name = f'1ДФ {rec.year} Q{rec.quarter}'

    @api.depends('line_ids.accrued_amount', 'line_ids.paid_amount', 
                 'line_ids.pdfo_amount', 'line_ids.military_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_employees = len(rec.line_ids)
            rec.total_accrued = sum(rec.line_ids.mapped('accrued_amount'))
            rec.total_paid = sum(rec.line_ids.mapped('paid_amount'))
            rec.total_pdfo = sum(rec.line_ids.mapped('pdfo_amount'))
            rec.total_military = sum(rec.line_ids.mapped('military_amount'))

    def action_generate(self):
        """Generate report lines from payslips"""
        self.ensure_one()
        self.line_ids.unlink()
        
        quarter_months = {
            '1': [1, 2, 3],
            '2': [4, 5, 6],
            '3': [7, 8, 9],
            '4': [10, 11, 12],
        }
        months = quarter_months[self.quarter]
        
        date_from = fields.Date.from_string(f'{self.year}-{months[0]:02d}-01')
        # The real last day of the quarter: payslips end on the 30th/31st.
        date_to = date_from + relativedelta(months=3, days=-1)
        
        # Get all payslips for the quarter
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', '=', 'done'),
        ])
        
        # Group by employee
        employee_data = {}
        for slip in payslips:
            emp_id = slip.employee_id.id
            if emp_id not in employee_data:
                employee_data[emp_id] = {
                    'employee_id': emp_id,
                    'accrued': 0,
                    'paid': 0,
                    'pdfo': 0,
                    'military': 0,
                }
            employee_data[emp_id]['accrued'] += slip.gross_salary
            employee_data[emp_id]['paid'] += slip.net_salary
            employee_data[emp_id]['pdfo'] += slip.pdfo_amount
            employee_data[emp_id]['military'] += slip.military_tax_amount
        
        # Create lines
        for emp_id, data in employee_data.items():
            employee = self.env['hr.employee'].browse(emp_id)

            # Get hire and termination dates from employee version (contract)
            date_hire = False
            date_termination = False

            version = employee.current_version_id
            if version:
                contract_start = version.contract_date_start
                contract_end = getattr(version, 'contract_date_end', None)

                # Include hire date if employee was hired during this quarter
                if contract_start and date_from <= contract_start <= date_to:
                    date_hire = contract_start

                # Include termination date if employee was terminated during this quarter
                if contract_end and date_from <= contract_end <= date_to:
                    date_termination = contract_end

            # In 1DF report, accrued and paid amounts are the same (as per Ukrainian law)
            accrued = data['accrued']

            self.env['hr.report.1df.line'].create({
                'report_id': self.id,
                'employee_id': emp_id,
                'rnokpp': employee.rnokpp or '',
                'income_type': '101',
                'accrued_amount': accrued,
                'paid_amount': accrued,  # Paid = Accrued in 1DF
                'pdfo_amount': data['pdfo'],
                'military_amount': data['military'],
                'date_hire': date_hire,
                'date_termination': date_termination,
            })
        
        self.write({'state': 'generated'})
        return True

    def action_submit(self):
        self.write({
            'state': 'submitted',
            'submission_date': fields.Date.today(),
        })

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_quarter_company_id = models.Constraint(
        'unique(year, quarter, company_id)',
        '1DF report for this period already exists!',
    )


class HrReport1DFLine(models.Model):
    _name = 'hr.report.1df.line'
    _description = '1DF Report Line'
    _order = 'employee_id'

    report_id = fields.Many2one(
        'hr.report.1df',
        string='Report',
        required=True,
        ondelete='cascade'
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True
    )
    rnokpp = fields.Char(string='RNOKPP', required=True)
    
    income_type = fields.Char(
        string='Income Type',
        default='101',
        help='Income type code for 1DF'
    )
    income_sign = fields.Selection([
        ('0', 'Accrued and Paid'),
        ('1', 'Accrued Only'),
    ], string='Income Sign', default='0')
    
    accrued_amount = fields.Float(string='Accrued Amount')
    paid_amount = fields.Float(string='Paid Amount')
    pdfo_amount = fields.Float(string='PDFO Amount')
    military_amount = fields.Float(string='Military Tax Amount')
    
    date_hire = fields.Date(string='Hire Date')
    date_termination = fields.Date(string='Termination Date')
    
    notes = fields.Char(string='Notes')
