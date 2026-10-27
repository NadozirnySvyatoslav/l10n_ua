from odoo import models, fields


class HrSickLeave(models.Model):
    _inherit = 'hr.sick.leave'

    fss_settlement_id = fields.Many2one(
        'hr.fss.settlement', string='PFU Settlement', copy=False,
        help='Заява-розрахунок ПФУ, до якої включено цей лікарняний.')
