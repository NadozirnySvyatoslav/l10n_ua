import base64

from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class L10nUaBankPayment(models.Model):
    """Вихідне платіжне доручення / пакет із КЕП-підписом (#199).

    Формує платіжний файл (пакет доручень), підписує його КЕП на стороні
    браузера через ``l10n_ua.sign.mixin`` (ключ/пароль не покидають клієнт)
    і фіксує стан підписано/відправлено. Фактична передача у банк —
    завантаження підписаного пакета в клієнт-банк (або API-провайдер).
    """
    _name = 'l10n_ua.bank.payment'
    _description = 'Bank Payment Order (КЕП)'
    _inherit = ['mail.thread', 'l10n_ua.sign.mixin']
    _order = 'payment_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, default='New', copy=False,
        tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    payer_account_id = fields.Many2one(
        'res.partner.bank', string='Payer Account', required=True,
        tracking=True)
    payment_date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
        tracking=True)
    file_format = fields.Selection(
        [('xml', 'XML (узагальнений пакет)')],
        string='Format', default='xml', required=True)

    line_ids = fields.One2many(
        'l10n_ua.bank.payment.line', 'payment_id', string='Payments')
    total_amount = fields.Monetary(
        string='Total', compute='_compute_total', store=True,
        currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id')

    file_data = fields.Binary(string='Payment File', readonly=True, copy=False)
    file_name = fields.Char(string='File Name', readonly=True, copy=False)
    signature_data = fields.Binary(
        string='КЕП Signature', readonly=True, copy=False)
    signer_info = fields.Char(string='Signed By', readonly=True, copy=False)
    receipt = fields.Char(string='Bank Receipt', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'File Generated'),
        ('signed', 'Signed'),
        ('sent', 'Sent'),
    ], string='Status', default='draft', tracking=True, copy=False)

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.bank.payment') or 'New'
        return super().create(vals_list)

    def _company_edrpou(self):
        company = self.company_id
        return (getattr(company, 'company_registry', False)
                or (company.vat or '').replace('UA', '').strip() or '')

    def _render_xml(self):
        """Узагальнений XML-пакет платіжних доручень (windows-1251)."""
        self.ensure_one()
        root = etree.Element('PaymentOrder')
        root.set('company', self.company_id.name or '')
        root.set('edrpou', self._company_edrpou())
        root.set('payer_account',
                 (self.payer_account_id.acc_number or '').replace(' ', ''))
        root.set('date', self.payment_date.strftime('%d.%m.%Y'))
        root.set('count', str(len(self.line_ids)))
        root.set('total', '%.2f' % self.total_amount)
        for line in self.line_ids:
            p = etree.SubElement(root, 'Payment')
            etree.SubElement(p, 'Recipient').text = line.recipient_name or ''
            etree.SubElement(p, 'Edrpou').text = line.recipient_edrpou or ''
            etree.SubElement(p, 'Account').text = (
                line.recipient_iban or '').replace(' ', '')
            etree.SubElement(p, 'Amount').text = '%.2f' % line.amount
            etree.SubElement(p, 'Purpose').text = line.purpose or ''
        return etree.tostring(
            root, xml_declaration=True, encoding='windows-1251',
            pretty_print=True)

    def _check_ready(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Додайте хоча б одне платіжне доручення.'))
        if not self.payer_account_id.acc_number:
            raise UserError(_('У рахунку платника не заповнено номер/IBAN.'))
        for line in self.line_ids:
            if line.amount <= 0:
                raise UserError(_('Сума платежу має бути додатною (рядок «%s»).')
                                % (line.recipient_name or ''))
            if not line.recipient_iban:
                raise UserError(_('Не вказано рахунок отримувача «%s».')
                                % (line.recipient_name or ''))

    def action_generate_file(self):
        self.ensure_one()
        self._check_ready()
        content = self._render_xml()
        self.write({
            'file_data': base64.b64encode(content).decode(),
            'file_name': 'payment_%s.xml' % (self.name or 'order').replace(
                '/', '_'),
            'state': 'generated',
        })
        return True

    def action_mark_sent(self):
        for rec in self:
            if rec.state != 'signed':
                raise UserError(_('Спершу підпишіть пакет КЕП.'))
            rec.state = 'sent'
        return True

    # --- l10n_ua.sign.mixin ---
    def kep_prepare_signing(self):
        self.ensure_one()
        if self.state == 'draft' or not self.file_data:
            self.action_generate_file()
        return {
            'auth_subject': None,
            'documents': [{
                'name': 'payment',
                'data_b64': self.file_data.decode()
                if isinstance(self.file_data, bytes) else self.file_data,
                'format': 'cades',
                'filename': self.file_name or 'payment.xml',
            }],
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        signature = (signed or {}).get('payment')
        if not signature:
            raise UserError(_('Не отримано підпис платіжного пакета.'))
        self.write({
            'signature_data': signature,
            'state': 'signed',
        })
        self.message_post(body=_('Платіжний пакет підписано КЕП.'))
        return {'ok': True, 'state': 'signed'}
