from odoo import models, fields


class HrDeductionType(models.Model):
    _name = 'hr.deduction.type'
    _description = 'Deduction Type'
    _order = 'priority, sequence, code'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    
    category = fields.Selection([
        ('tax', 'Tax'),
        ('social', 'Social Contribution'),
        ('union', 'Union Fees'),
        ('alimony', 'Alimony'),
        ('loan', 'Loan Repayment'),
        ('advance', 'Advance Deduction'),
        ('damage', 'Damage Compensation'),
        ('other', 'Other'),
    ], string='Category', required=True, default='other')
    
    calculation_method = fields.Selection([
        ('percent_gross', 'Percent of Gross'),
        ('percent_net', 'Percent of Net'),
        ('percent_base', 'Percent of Tax Base'),
        ('fixed', 'Fixed Amount'),
    ], string='Calculation Method', default='percent_gross')
    
    default_rate = fields.Float(string='Default Rate (%)')
    default_amount = fields.Float(string='Default Amount')
    
    priority = fields.Integer(
        string='Priority',
        default=10,
        help='Deduction priority (lower = first). Alimony has priority 1-3.'
    )
    
    max_percent = fields.Float(
        string='Max Percent of Salary',
        help='Maximum percent that can be deducted (50% or 70% for alimony)'
    )
    
    is_mandatory = fields.Boolean(
        string='Mandatory',
        help='Automatically applied to all payslips'
    )
    
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'Deduction type code must be unique!',
    )
