from odoo import models, fields, api


class HrPayslipAccrual(models.Model):
    _name = 'hr.payslip.accrual'
    _description = 'Payslip Accrual'
    _order = 'sequence, id'

    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        required=True,
        ondelete='cascade'
    )
    accrual_type_id = fields.Many2one(
        'hr.accrual.type',
        string='Accrual Type',
        required=True
    )
    sequence = fields.Integer(
        string='Sequence',
        related='accrual_type_id.sequence',
        store=True
    )
    
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        help='Days, hours, or units'
    )
    rate = fields.Float(
        string='Rate',
        help='Rate per unit (hourly/daily rate)'
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='payslip_id.currency_id'
    )
    
    is_taxable_pdfo = fields.Boolean(
        string='Taxable (PDFO)',
        related='accrual_type_id.is_taxable_pdfo'
    )
    is_military_tax = fields.Boolean(
        string='Military Tax',
        related='accrual_type_id.is_military_tax'
    )
    is_esv_base = fields.Boolean(
        string='ESV Base',
        related='accrual_type_id.is_esv_base'
    )
    is_in_kind = fields.Boolean(
        string='In-Kind Income',
        related='accrual_type_id.is_in_kind'
    )

    d4_income_type = fields.Char(
        string='4DF Income Type',
        related='accrual_type_id.d4_income_type'
    )
    
    notes = fields.Char(string='Notes')

    period_month = fields.Date(
        string='Period Month',
        help='The month the amount is for, when it is not the month of the '
             'payslip: a sickness benefit accrued in the month its certificate '
             'was confirmed may be for the days of an earlier month. Empty '
             'means the month of the payslip.'
    )

    l10n_ua_bonus_period_to = fields.Date(
        string='Bonus For Period Ending',
        help='For a bonus for a quarter, half-year or year: the last month of '
             'the period it is for, when that is not the month of the payslip '
             '(a bonus for the first quarter accrued in April: March). The '
             'average salary divides the bonus by the working days worked in '
             'that period (Порядок № 100, п. 3, абз. 3).')

    is_auto_generated = fields.Boolean(
        string='Auto-generated',
        default=False,
        help='Indicates if this accrual was automatically generated during payslip computation. '
             'Auto-generated accruals are recreated on recomputation, manual ones are preserved.'
    )
