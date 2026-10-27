import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Common states of a document in an EDO service; a provider maps its own
# statuses onto them (``provider_status`` keeps the original one).
EDO_STATES = [
    ('draft', 'Not Sent'),
    ('uploaded', 'Uploaded'),
    ('sent', 'Sent for Signature'),
    ('signing', 'Being Signed'),
    ('signed_owner', 'Signed by Sender'),
    ('signed', 'Signed by All'),
    ('rejected', 'Rejected'),
    ('deleted', 'Deleted'),
]


class L10nUaEdoDocument(models.Model):
    _name = 'l10n_ua.edo.document'
    _description = 'EDO Document'
    _inherit = ['mail.thread', 'l10n_ua.sign.mixin']
    _order = 'date desc, id desc'

    _FINAL_STATES = ('signed', 'rejected', 'deleted')

    name = fields.Char(string='Title', required=True)
    account_id = fields.Many2one('l10n_ua.edo.account', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='account_id.company_id', store=True, index=True)
    provider = fields.Selection(related='account_id.provider')
    direction = fields.Selection(
        [('out', 'Outgoing'), ('in', 'Incoming')], required=True, default='out', index=True)
    provider_ref = fields.Char(string='ID in the Service', copy=False, index=True)
    provider_status = fields.Char(string='Status in the Service', copy=False)
    state = fields.Selection(EDO_STATES, default='draft', required=True, tracking=True, index=True)
    url = fields.Char(string='Link', copy=False)
    number = fields.Char()
    date = fields.Date()
    amount = fields.Float(digits=(16, 2))
    category = fields.Char()
    counterparty_edrpou = fields.Char(string='Counterparty ЄДРПОУ', index=True)
    counterparty_name = fields.Char()
    partner_id = fields.Many2one('res.partner', string='Counterparty')
    res_model = fields.Char(string='Document Model', index=True, copy=False)
    res_id = fields.Many2oneReference(string='Document ID', model_field='res_model', copy=False)
    attachment_id = fields.Many2one('ir.attachment', string='Original', copy=False)
    archive_attachment_id = fields.Many2one('ir.attachment', string='Archive with Signatures', copy=False)
    last_sync = fields.Datetime(copy=False)
    can_sign = fields.Boolean(
        compute='_compute_capabilities',
        help='The company signs the document now: it is its turn in the service.')
    can_extract = fields.Boolean(
        compute='_compute_capabilities',
        help='The service can recognise the lines and totals of the document.')
    data_state = fields.Selection([
        ('pending', 'Being Recognised'),
        ('awaiting_validation', 'Recognised, to Confirm in the Service'),
        ('confirmed', 'Confirmed'),
        ('downloaded', 'Exported'),
        ('error', 'Recognition Error'),
    ], string='Recognised Data', copy=False,
        help='Recognition of the lines and totals of the document in the service.')

    _provider_ref_uniq = models.Constraint(
        'UNIQUE(account_id, provider_ref)',
        'A document of the service is linked only once per EDO account.',
    )

    # ── Provider values ─────────────────────────────────────

    def _apply_provider_vals(self, vals):
        """Write normalised provider values and let the linked record react."""
        for doc in self:
            old_state = doc.state
            vals = dict(vals, last_sync=fields.Datetime.now())
            vals.pop('direction', None)
            doc.write({k: v for k, v in vals.items() if k in self._fields})
            if doc.state != old_state:
                # The archive first: the record may want to keep it
                if doc.state == 'signed' and not doc.archive_attachment_id:
                    doc._fetch_file('archive')
                record = doc._record()
                if record and hasattr(record, '_edo_on_state'):
                    record._edo_on_state(doc)

    @api.model
    def _upsert_incoming(self, account, vals):
        """Create or update an incoming document; find the counterparty by ЄДРПОУ."""
        doc = self.search([('account_id', '=', account.id),
                           ('provider_ref', '=', vals.get('provider_ref'))], limit=1)
        if doc:
            doc._apply_provider_vals(vals)
            return doc
        vals = dict(vals, account_id=account.id, direction='in', last_sync=fields.Datetime.now())
        if not vals.get('partner_id') and vals.get('counterparty_edrpou'):
            vals['partner_id'] = self._find_partner(vals['counterparty_edrpou']).id or False
        doc = self.create({k: v for k, v in vals.items() if k in self._fields})
        doc.message_post(body=_('Incoming document imported from the EDO service.'))
        return doc

    @api.model
    def _find_partner(self, edrpou):
        Partner = self.env['res.partner']
        if not edrpou or 'edrpou' not in Partner._fields:
            return Partner
        return Partner.search([('edrpou', '=', edrpou), ('is_company', '=', True)], limit=1) \
            or Partner.search([('edrpou', '=', edrpou)], limit=1)

    @api.depends('state', 'provider_status', 'direction', 'account_id.provider')
    def _compute_capabilities(self):
        for doc in self:
            account = doc.account_id
            method = account.provider and getattr(account, f'_{account.provider}_can_sign', None)
            doc.can_sign = bool(doc.provider_ref and method and method(doc))
            doc.can_extract = bool(doc.provider_ref and account.provider
                                   and hasattr(account, f'_{account.provider}_extract'))

    # ── Files ───────────────────────────────────────────────

    def _fetch_file(self, kind):
        self.ensure_one()
        if not self.provider_ref:
            raise UserError(_('The document is not in the EDO service yet.'))
        filename, content = self.account_id._call('download', self.provider_ref, kind)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'datas': base64.b64encode(content),
            'res_model': self._name,
            'res_id': self.id,
        })
        field = 'archive_attachment_id' if kind == 'archive' else 'attachment_id'
        self[field] = attachment
        record = self._record()
        if record and kind == 'archive':
            attachment.copy({'res_model': record._name, 'res_id': record.id})
        return attachment

    def _download_action(self, attachment):
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_download_original(self):
        self.ensure_one()
        return self._download_action(self.attachment_id or self._fetch_file('original'))

    def action_download_archive(self):
        self.ensure_one()
        return self._download_action(self.archive_attachment_id or self._fetch_file('archive'))

    # ── Actions ─────────────────────────────────────────────

    def action_refresh(self):
        for account in self.account_id:
            docs = self.filtered(lambda d: d.account_id == account and d.provider_ref)
            by_ref = {doc.provider_ref: doc for doc in docs}
            for data in account._call('fetch', list(by_ref)):
                vals = account._call('normalize', data)
                if vals.get('provider_ref') in by_ref:
                    by_ref[vals['provider_ref']]._apply_provider_vals(vals)
        return True

    def action_open_in_service(self):
        self.ensure_one()
        if not self.url:
            raise UserError(_('The service gave no link to this document.'))
        return {'type': 'ir.actions.act_url', 'url': self.url, 'target': 'new'}

    # ── КЕП signature ───────────────────────────────────────

    def action_edo_sign(self):
        """Sign the document with КЕП in the browser and hand the signature to the service."""
        self.ensure_one()
        if self.can_sign:
            self.action_refresh()  # the status may have moved on in the service
        if not self.can_sign:
            raise UserError(_('It is not the turn of your company to sign document «%s».', self.name))
        return self.action_kep_sign()

    def kep_prepare_signing(self):
        self.ensure_one()
        attachment = self.attachment_id or self._fetch_file('original')
        if self.direction == 'out':
            description = _('The signature goes to the service, then the document is sent to the counterparty.')
        else:
            description = _('The signature goes to the service as the signature of the recipient.')
        return {
            'description': description,
            'documents': [{
                'name': 'document',
                'data_b64': attachment.datas.decode(),
                'format': 'cades_detached',
                'filename': attachment.name,
            }],
        }

    def kep_submit_signed(self, signed, auth_signature=None):
        self.ensure_one()
        signature = (signed or {}).get('document')
        if not signature:
            raise UserError(_('The browser returned no signature.'))
        account = self.account_id
        account._call('sign', self.provider_ref, signature)
        self.message_post(body=_('Signed with КЕП in Odoo.'))
        receipt = _('Signed.')
        if self.direction == 'out':
            try:
                account._call('send', self.provider_ref)
            except UserError as error:
                # The signature is in the service already; sending is retried there
                self.message_post(body=_('Signed, but not sent: %s', error))
                receipt = _('Signed, but not sent: %s', error)
            else:
                self.message_post(body=_('Sent to the counterparty.'))
                receipt = _('Signed and sent to the counterparty.')
        self.action_refresh()
        return {'receipt': receipt}

    def _record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return None
        record = self.env[self.res_model].browse(self.res_id).exists()
        return record or None

    def action_open_record(self):
        self.ensure_one()
        record = self._record()
        if not record:
            raise UserError(_('The document is not linked to a record in Odoo.'))
        return {
            'type': 'ir.actions.act_window', 'res_model': record._name,
            'res_id': record.id, 'view_mode': 'form',
        }
