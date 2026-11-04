from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_ua_import_declaration_ids = fields.Many2many(
        'l10n_ua.import.declaration', 'l10n_ua_import_declaration_move_rel', 'move_id', 'declaration_id',
        string='Import Customs Declarations', copy=False)

    def action_view_l10n_ua_import_declarations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.import.declaration',
            'name': self.env._('Import Customs Declarations'),
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.l10n_ua_import_declaration_ids.ids)],
            'context': {'default_bill_ids': [(6, 0, self.ids)], 'default_partner_id': self.commercial_partner_id.id,
                        'default_agreement_id': self.l10n_ua_agreement_id.id},
        }
