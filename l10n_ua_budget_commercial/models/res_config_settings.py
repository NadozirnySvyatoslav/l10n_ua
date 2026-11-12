from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_ua_budget_control = fields.Selection(
        related='company_id.l10n_ua_budget_control', readonly=False,
    )
