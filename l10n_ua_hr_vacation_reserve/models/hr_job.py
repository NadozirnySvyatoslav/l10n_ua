from odoo import fields, models


class HrJob(models.Model):
    _inherit = 'hr.job'

    vacation_reserve_expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат на резерв',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Рахунок витрат, на який списується резерв відпусток для цієї '
             'посади (23 — виробництво, 91 — адмін, 92 — збут, 93 — інші '
             'операційні). Якщо не задано — береться з компанії.',
    )
