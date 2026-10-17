from odoo import _, api, fields, models


class L10nUaAgreement(models.Model):
    _inherit = 'l10n_ua.agreement'

    contract_ids = fields.One2many(
        'contract.contract', 'l10n_ua_agreement_id', string='Recurring Contracts')
    contract_count = fields.Integer(compute='_compute_contract_count')

    @api.depends('contract_ids')
    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = len(rec.contract_ids)

    def action_create_contract(self):
        self.ensure_one()
        contract = self.env['contract.contract'].create({
            'name': self.display_name,
            'partner_id': self.partner_id.id,
            'l10n_ua_agreement_id': self.id,
            'contract_type': self.direction,
            'company_id': self.company_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recurring Contract'),
            'res_model': 'contract.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recurring Contracts'),
            'res_model': 'contract.contract',
            'view_mode': 'list,form',
            'domain': [('l10n_ua_agreement_id', '=', self.id)],
            'context': {'default_l10n_ua_agreement_id': self.id},
        }
