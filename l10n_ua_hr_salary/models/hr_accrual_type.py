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
    
    # Порядок № 100, п. 3: every accrued wage counts unless п. 4 names it,
    # so a new type is in the base until it is marked otherwise.
    is_basic_salary = fields.Boolean(
        string='Basic Salary Component',
        default=True,
        help='Include in the average salary for vacations and their '
             'compensation (Порядок № 100, п. 3). Clear it for the payments '
             'of п. 4: one-off payments (compensation for unused vacation, '
             'material aid, severance pay), social payments, payments in kind. '
             'Vacation pay and sickness benefits are counted for a vacation '
             'by their category. The sick-leave average does not read this '
             'flag: it takes the pay in the contribution base (ESV Base), '
             'per Порядок № 1266.'
    )
    l10n_ua_bonus_months = fields.Selection(
        [('1', 'Month'), ('3', 'Quarter'), ('6', 'Half-Year'), ('12', 'Year')],
        string='Bonus Period', default='1', required=True,
        help='For a bonus: the period it is paid for. A bonus for a quarter, '
             'half-year or year counts in the average salary for vacations '
             'spread over as many months, counting back from the month it is '
             'accrued in, pro rata to the working days worked (Порядок № 100, '
             'п. 3, абз. 3).')
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
