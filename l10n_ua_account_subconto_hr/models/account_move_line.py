"""HR department as a subconto dimension on journal items."""

from odoo import api, models, fields


class L10nUaSubcontoType(models.Model):
    _inherit = 'l10n_ua.subconto.type'

    @api.model
    def _selection_subconto_models(self):
        return super()._selection_subconto_models() + [
            ('hr.department', self.env['hr.department']._description),
        ]


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    subconto_department_id = fields.Many2one(
        'hr.department',
        string='Department (Subconto)',
        compute='_compute_subconto_quick_fields',
        inverse='_inverse_subconto_department',
        store=True,
    )

    def _subconto_quick_fields_map(self):
        return {
            **super()._subconto_quick_fields_map(),
            'hr.department': 'subconto_department_id',
        }

    def _inverse_subconto_department(self):
        self._set_subconto_value('hr.department', 'subconto_department_id')
