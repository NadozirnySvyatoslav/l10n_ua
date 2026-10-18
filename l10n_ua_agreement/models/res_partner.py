from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_ua_agreement_count = fields.Integer(compute='_compute_l10n_ua_agreement_count')

    def _compute_l10n_ua_agreement_count(self):
        counts = dict(self.env['l10n_ua.agreement']._read_group(
            [('commercial_partner_id', 'in', self.commercial_partner_id.ids)],
            ['commercial_partner_id'], ['__count']))
        for partner in self:
            partner.l10n_ua_agreement_count = counts.get(partner.commercial_partner_id, 0)

    def action_view_l10n_ua_agreements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agreements'),
            'res_model': 'l10n_ua.agreement',
            'view_mode': 'list,form',
            'domain': [('commercial_partner_id', '=', self.commercial_partner_id.id)],
            'context': {'default_partner_id': self.id},
        }
