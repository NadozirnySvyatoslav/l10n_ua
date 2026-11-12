from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_budget_control = fields.Selection(
        [('none', 'Disabled'), ('warning', 'Warning'), ('block', 'Block')],
        string='Budget Control on Vendor Bills', default='none', required=True,
        help='What happens when a posted vendor bill makes an approved Income & '
             'Expense budget line exceed its plan:\n'
             '- Disabled: nothing;\n'
             '- Warning: the bill is posted and a note is logged on it;\n'
             '- Block: the bill cannot be posted.',
    )
