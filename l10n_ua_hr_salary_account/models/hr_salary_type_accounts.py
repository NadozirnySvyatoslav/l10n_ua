from odoo import fields, models


# The accounts of an accrual or a deduction type need the accounting app,
# which the payroll module does not depend on: they live here, next to the
# journal entries of the payroll.

class HrAccrualType(models.Model):
    _inherit = 'hr.accrual.type'

    account_debit_id = fields.Many2one(
        'account.account',
        string='Debit Account',
        help='Expense account'
    )
    account_credit_id = fields.Many2one(
        'account.account',
        string='Credit Account',
        help='Liability account'
    )


class HrDeductionType(models.Model):
    _inherit = 'hr.deduction.type'

    account_debit_id = fields.Many2one(
        'account.account',
        string='Debit Account'
    )
    account_credit_id = fields.Many2one(
        'account.account',
        string='Credit Account'
    )
