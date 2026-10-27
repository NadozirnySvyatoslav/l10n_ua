import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaEdoDocument(models.Model):
    _inherit = 'l10n_ua.edo.document'

    can_create_bill = fields.Boolean(compute='_compute_can_create_bill')

    @api.depends('direction', 'category', 'account_id.provider')
    def _compute_can_create_bill(self):
        for doc in self:
            doc.can_create_bill = doc.direction == 'in' and doc._is_bill_category()

    def _is_bill_category(self):
        """Whether the category of the document is one a vendor bill comes from.

        A document without a category, or a service that does not tell its bill
        categories, is let through: the user decides."""
        self.ensure_one()
        account = self.account_id
        method = account.provider and getattr(account, f'_{account.provider}_bill_categories', None)
        if not method or not self.category or self.category == '0':
            return True
        return self.category in method()

    def action_create_vendor_bill(self):
        """A draft vendor bill from an incoming document, with its PDF."""
        self.ensure_one()
        if self.direction != 'in':
            raise UserError(_('Only an incoming document becomes a vendor bill.'))
        if not self._is_bill_category():
            raise UserError(_('A vendor bill is made from an invoice, an act or a waybill, '
                              'not from a document of this category (a contract, for example).'))
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
