from odoo import fields, models


class L10nUaEdoKepRejectWizard(models.TransientModel):
    _name = 'l10n_ua.edo.kep.reject.wizard'
    _description = 'Reject a КЕП Document'

    document_id = fields.Many2one('l10n_ua.edo.document', required=True, ondelete='cascade')
    reason = fields.Text(required=True)

    def action_reject(self):
        self.ensure_one()
        self.document_id._kep_reject(self.reason, by_counterparty=False)
        return {'type': 'ir.actions.act_window_close'}
