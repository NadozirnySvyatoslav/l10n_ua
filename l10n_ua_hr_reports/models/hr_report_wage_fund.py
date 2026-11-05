from odoo import models, fields, api


class HrReportWageFund(models.Model):
    """Wage Fund Report (Звіт про фонд оплати праці)

    Analyzes wage fund structure by accrual types:
    - Basic salary fund
    - Additional wage fund (bonuses, allowances)
    - Other payments
    - Tax deductions
    """
    _name = 'hr.report.wage_fund'
    _description = 'Wage Fund Report'
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

    # Summary totals
    total_employees = fields.Integer(
        string='Total Employees',
        help='Number of employees with payslips'
    )
    total_gross = fields.Monetary(
        string='Total Gross',
        currency_field='currency_id',
        help='Total accrued amount (gross salary)'
    )
    total_net = fields.Monetary(
        string='Total Net',
        currency_field='currency_id',
        help='Total net salary (after deductions)'
    )

    # Wage fund breakdown
    fund_basic_salary = fields.Monetary(
        string='Basic Salary Fund',
        currency_field='currency_id',
        help='Base salary accruals'
    )
    fund_allowances = fields.Monetary(
        string='Allowances Fund',
        currency_field='currency_id',
        help='Allowances and supplements'
    )
    fund_bonuses = fields.Monetary(
        string='Bonuses Fund',
        currency_field='currency_id',
        help='Bonuses and premiums'
    )
    fund_other = fields.Monetary(
        string='Other Payments',
        currency_field='currency_id',
        help='Other accruals'
    )

    # Tax deductions
    total_pdfo = fields.Monetary(
        string='Total PDFO',
        currency_field='currency_id',
        help='Personal income tax (18%)'
    )
    total_military = fields.Monetary(
        string='Total Military Tax',
        currency_field='currency_id',
        help='Military tax (5%)'
    )
    total_esv = fields.Monetary(
        string='Total ESV',
        currency_field='currency_id',
        help='Unified social contribution (22%)'
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    line_ids = fields.One2many(
        'hr.report.wage_fund.line',
        'report_id',
        string='Employee Details'
    )

    accrual_summary_ids = fields.One2many(
        'hr.report.wage_fund.accrual',
        'report_id',
        string='Accrual Summary'
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
            rec.name = f'Фонд оплати праці {month_name} {rec.year}'

    def action_generate(self):
        """Generate wage fund report from payslips"""
        self.ensure_one()
        self.line_ids.unlink()
        self.accrual_summary_ids.unlink()

        month_int = int(self.month)
        date_from = fields.Date.from_string(f'{self.year}-{month_int:02d}-01')

        # Calculate last day of month
        if month_int == 12:
            date_to = fields.Date.from_string(f'{self.year + 1}-01-01')
        else:
            date_to = fields.Date.from_string(f'{self.year}-{month_int + 1:02d}-01')

        # Get payslips for the month
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<', date_to),
            ('state', '=', 'done'),
        ])

        if not payslips:
            self.write({'state': 'generated'})
            return True

        # Totals
        total_gross = 0
        total_net = 0
        total_pdfo = 0
        total_military = 0
        total_esv = 0

        fund_salary = 0
        fund_allowances = 0
        fund_bonuses = 0
        fund_other = 0

        accrual_totals = {}  # {accrual_type_id: total_amount}

        for slip in payslips:
            # Create employee line
            self.env['hr.report.wage_fund.line'].create({
                'report_id': self.id,
                'employee_id': slip.employee_id.id,
                'department_id': slip.employee_id.department_id.id if slip.employee_id.department_id else False,
                'gross_salary': slip.gross_salary,
                'net_salary': slip.net_salary,
                'pdfo_amount': slip.pdfo_amount,
                'military_amount': slip.military_tax_amount,
                'esv_amount': slip.esv_amount,
            })

            total_gross += slip.gross_salary
            total_net += slip.net_salary
            total_pdfo += slip.pdfo_amount
            total_military += slip.military_tax_amount
            total_esv += slip.esv_amount

            # Analyze accruals by type
            for accrual in slip.accrual_ids:
                accrual_type = accrual.accrual_type_id
                amount = accrual.amount

                # Track by type
                if accrual_type.id not in accrual_totals:
                    accrual_totals[accrual_type.id] = 0
                accrual_totals[accrual_type.id] += amount

                # Categorize into funds
                code = accrual_type.code if accrual_type else ''
                if code == 'SALARY':
                    fund_salary += amount
                elif code == 'ALLOWANCE':
                    fund_allowances += amount
                elif code in ('BONUS', 'PREMIUM') or accrual_type.category == 'bonus':
                    fund_bonuses += amount
                else:
                    fund_other += amount

        # Create accrual summary lines
        for accrual_type_id, total in accrual_totals.items():
            self.env['hr.report.wage_fund.accrual'].create({
                'report_id': self.id,
                'accrual_type_id': accrual_type_id,
                'total_amount': total,
            })

        # Update totals
        self.write({
            'total_employees': len(payslips.mapped('employee_id')),
            'total_gross': total_gross,
            'total_net': total_net,
            'total_pdfo': total_pdfo,
            'total_military': total_military,
            'total_esv': total_esv,
            'fund_basic_salary': fund_salary,
            'fund_allowances': fund_allowances,
            'fund_bonuses': fund_bonuses,
            'fund_other': fund_other,
            'state': 'generated',
        })

        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_month_company_id = models.Constraint(
        'unique(year, month, company_id)',
        'Wage fund report for this period already exists!',
    )


class HrReportWageFundLine(models.Model):
    _name = 'hr.report.wage_fund.line'
    _description = 'Wage Fund Report Employee Line'
    _order = 'employee_id'

    report_id = fields.Many2one(
        'hr.report.wage_fund',
        string='Report',
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
        string='Department'
    )

    gross_salary = fields.Monetary(
        string='Gross Salary',
        currency_field='currency_id'
    )
    net_salary = fields.Monetary(
        string='Net Salary',
        currency_field='currency_id'
    )
    pdfo_amount = fields.Monetary(
        string='PDFO',
        currency_field='currency_id'
    )
    military_amount = fields.Monetary(
        string='Military Tax',
        currency_field='currency_id'
    )
    esv_amount = fields.Monetary(
        string='ESV',
        currency_field='currency_id'
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='report_id.currency_id'
    )


class HrReportWageFundAccrual(models.Model):
    _name = 'hr.report.wage_fund.accrual'
    _description = 'Wage Fund Accrual Summary'
    _order = 'total_amount desc'

    report_id = fields.Many2one(
        'hr.report.wage_fund',
        string='Report',
        required=True,
        ondelete='cascade'
    )
    accrual_type_id = fields.Many2one(
        'hr.accrual.type',
        string='Accrual Type',
        required=True
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='report_id.currency_id'
    )
