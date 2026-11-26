import logging

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        lines = self._bill_line_vals()
        bill = self.env['account.move'].with_company(self.company_id).create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'ref': self.number or self.name,
            'invoice_date': self.date,
            'company_id': self.company_id.id,
            'invoice_line_ids': [Command.create(vals) for vals in lines],
        })
        attachment = self.attachment_id or self._fetch_file('original')
        copy = attachment.copy({'res_model': bill._name, 'res_id': bill.id})
        if lines:
            note = _('Created from the EDO document «%(name)s»: %(count)s lines from the data recognised '
                     'in the service. Check them against the PDF.', name=self.name, count=len(lines))
        else:
            note = _('Created from the EDO document «%s». The service has no confirmed data of it: '
                     'fill in the lines from the PDF.', self.name)
        bill.message_post(body=note, attachment_ids=copy.ids)
        self.write({'res_model': bill._name, 'res_id': bill.id})
        return {'type': 'ir.actions.act_window', 'res_model': bill._name,
                'res_id': bill.id, 'view_mode': 'form'}

    # ── Recognised data ─────────────────────────────────────

    def _structured_data(self):
        """The recognised data of the document from the service, or None."""
        account = self.account_id
        method = account.provider and getattr(account, f'_{account.provider}_structured_data', None)
        if not method or not self.provider_ref:
            return None
        try:
            return method(self.provider_ref)
        except UserError as error:
            # Recognition may be off in the tariff: the bill is still made, without lines
            _logger.info('EDO document %s: no recognised data: %s', self.id, error)
            return None

    def _bill_line_vals(self):
        """Lines of the vendor bill from the recognised data of the document.

        A VAT payer gets the price without VAT and the purchase tax of the rate;
        otherwise the price with VAT and no tax, so the total is what is paid."""
        data = self._structured_data()
        items = (data or {}).get('items') if isinstance(data, dict) else None
        if not items:
            return []
        company = self.company_id
        vat_payer = 'l10n_ua_is_vat_payer' in company._fields and company.l10n_ua_is_vat_payer
        Product = self.env['product.product'].with_company(company)
        lines = []
        for item in items:
            quantity = self._number(item.get('quantity')) or 1.0
            gross = self._number(item.get('price_with_vat'))
            net = self._number(item.get('price_without_vat'))
            total = self._number(item.get('total_price_with_vat')) or self._number(item.get('total_price_without_vat'))
            vals = {'name': item.get('name') or _('Item'), 'quantity': quantity}
            tax = vat_payer and net and self._purchase_tax(item.get('vat_rate'))
            if tax:
                vals.update(price_unit=net, tax_ids=[Command.set(tax.ids)])
            else:
                vals.update(price_unit=gross or net or (total / quantity if total else 0.0),
                            tax_ids=[Command.clear()])
            code = (item.get('code') or '').strip()
            product = code and Product.search([('default_code', '=', code)], limit=1)
            if product:
                vals['product_id'] = product.id
            lines.append(vals)
        return lines

    @staticmethod
    def _number(value):
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _purchase_tax(self, rate):
        rate = self._number(rate)
        if not rate:
            return self.env['account.tax']
        taxes = self.env['account.tax'].search([
            ('type_tax_use', '=', 'purchase'), ('amount_type', '=', 'percent'), ('amount', '=', rate),
            *self.env['account.tax']._check_company_domain(self.company_id)])
        return taxes.filtered(lambda t: not t.price_include)[:1]

    def action_edo_extract(self):
        """Ask the service to recognise the lines and totals of the documents."""
        for account in self.account_id:
            docs = self.filtered(lambda d: d.account_id == account and d.provider_ref and d.direction == 'in')
            if not docs:
                continue
            by_ref = {doc.provider_ref: doc for doc in docs}
            for result in account._call('extract', list(by_ref)) or []:
                doc = by_ref.get(str(result.get('document_id')))
                status = result.get('status')
                if doc and status in dict(doc._fields['data_state'].selection):
                    doc.data_state = status
            docs.message_post(body=_('Recognition of the data started in the service. When it is done, '
                                     'confirm the data there, then create the vendor bill.'))
        return True
