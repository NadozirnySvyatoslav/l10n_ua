import base64

from odoo import models, _
from odoo.exceptions import UserError


class L10nUaEdoDocument(models.Model):
    _inherit = 'l10n_ua.edo.document'

    def action_create_vendor_bill(self):
        """A draft vendor bill from an incoming document, with its PDF."""
        self.ensure_one()
        if self.direction != 'in':
            raise UserError(_('Only an incoming document becomes a vendor bill.'))
        if self._record():
            return self.action_open_record()
        if not self.partner_id:
            raise UserError(_('Set the counterparty of the document first (it was not found by ЄДРПОУ %s).',
                              self.counterparty_edrpou or '—'))
        bill = self.env['account.move'].with_company(self.company_id).create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'ref': self.number or self.name,
            'invoice_date': self.date,
            'company_id': self.company_id.id,
        })
        attachment = self.attachment_id or self._fetch_file('original')
        copy = attachment.copy({'res_model': bill._name, 'res_id': bill.id})
        bill.message_post(body=_('Created from the EDO document «%s».', self.name), attachment_ids=copy.ids)
        self.write({'res_model': bill._name, 'res_id': bill.id})
        return {'type': 'ir.actions.act_window', 'res_model': bill._name,
                'res_id': bill.id, 'view_mode': 'form'}
