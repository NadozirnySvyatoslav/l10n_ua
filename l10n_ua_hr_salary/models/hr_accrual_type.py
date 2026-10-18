from odoo import models, fields


class HrAccrualType(models.Model):
    _name = 'hr.accrual.type'
    _description = 'Accrual Type'
    _order = 'sequence, code'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    
    category = fields.Selection([
        ('wage', 'Base Wage'),
        ('allowance', 'Allowance'),
        ('bonus', 'Bonus'),
        ('vacation', 'Vacation Pay'),
        ('sick', 'Sick Leave'),
        ('maternity', 'Maternity Leave'),
        ('compensation', 'Compensation'),
        ('other', 'Other'),
    ], string='Category', required=True, default='wage')
    
    calculation_method = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('hourly', 'Hourly Rate'),
        ('daily', 'Daily Rate'),
        ('monthly', 'Monthly Salary'),
        ('percent', 'Percent of Base'),
    ], string='Calculation Method', default='monthly')
    
    is_basic_salary = fields.Boolean(
        string='Basic Salary Component',
        help='Include in average salary calculation'
    )
    is_taxable_pdfo = fields.Boolean(
        string='Taxable (PDFO)',
        default=True
    )
    is_military_tax = fields.Boolean(
        string='Military Tax',
        default=True
    )
    is_esv_base = fields.Boolean(
        string='ESV Base',
        default=True
    )
    is_in_kind = fields.Boolean(
        string='In-Kind Income',
        help='Дохід у натуральній (негрошовій) формі. До бази ПДФО (та ВЗ) '
             'застосовується натуральний коефіцієнт для гросс-апу (п. 164.5 ПКУ).'
    )

    d4_income_type = fields.Char(
        string='4DF Income Type Code',
        help='Income type code for 4DF report'
    )
    
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'Accrual type code must be unique!',
    )
