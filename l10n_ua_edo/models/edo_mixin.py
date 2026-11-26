from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .edo_document import EDO_STATES


class L10nUaEdoMixin(models.AbstractModel):
    """Sends a record to an EDO service and shows its status.

    A bridge module inherits this mixin on its model and overrides what
    differs from the defaults:

    * ``_edo_reports()`` — the PDF reports that can be sent (default: the
      reports of the model in the menu «Друк»);
    * ``_edo_partner()`` — the counterparty (default: ``partner_id``);
    * ``_edo_meta()`` — title, number, date, amount, currency, category;
    * ``_edo_on_state(edo_document)`` — reacts to a new state (default: a
      message in the chatter).
    """
    _name = 'l10n_ua.edo.mixin'
    _description = 'EDO: send a document'

    edo_document_ids = fields.Many2many(
        'l10n_ua.edo.document', compute='_compute_edo', string='EDO Documents')
    edo_document_count = fields.Integer(compute='_compute_edo', string='EDO Documents Count')
    edo_state = fields.Selection(EDO_STATES, compute='_compute_edo', string='EDO Status')

    def _compute_edo(self):
        Document = self.env['l10n_ua.edo.document']
        docs = Document.search([('res_model', '=', self._name), ('res_id', 'in', self.ids)]) \
            if self.ids else Document
        for record in self:
            mine = docs.filtered(lambda d: d.res_id == record.id)
            record.edo_document_ids = mine
            record.edo_document_count = len(mine)
            record.edo_state = mine.sorted('id', reverse=True)[:1].state or False

    # ── Hooks ───────────────────────────────────────────────

    def _edo_reports(self):
        """PDF reports of the model offered in the menu «Друк», the Ukrainian
        forms (modules l10n_ua*) first."""
        reports = self.env['ir.actions.report'].search([
            ('model', '=', self._name), ('report_type', '=', 'qweb-pdf'),
            ('binding_model_id', '!=', False)])
        xmlids = reports.get_external_id()
        return reports.sorted(lambda r: (not (xmlids.get(r.id) or '').startswith('l10n_ua'), r.name))

    def _edo_partner(self):
        self.ensure_one()
        partner = self['partner_id'] if 'partner_id' in self._fields else self.env['res.partner']
        return partner.commercial_partner_id

    def _edo_meta(self):
        self.ensure_one()
        return {
            'title': self.display_name,
            'number': self['name'] if 'name' in self._fields else False,
            'date': False,
            'amount': 0.0,
            'currency': False,
            'category': False,
        }

    def _edo_on_state(self, edo_document):
        state = dict(EDO_STATES).get(edo_document.state, edo_document.state)
        if hasattr(self, 'message_post'):
            self.message_post(body=_('EDO: «%(title)s» — %(state)s.',
                                     title=edo_document.name, state=state))

    # ── Sending ─────────────────────────────────────────────

    def _edo_render(self, report):
        self.ensure_one()
        content, _type = self.env['ir.actions.report']._render_qweb_pdf(report, self.ids)
        filename = (self.display_name or report.name).replace('/', '_') + '.pdf'
        return filename, content

    def _edo_send(self, account, report, recipient_edrpou, recipient_emails=None,
                  title=None, category=None, send=False):
        """Render and upload the record; return the EDO document.

        Without ``send`` the document waits in the service for the signature
        of the sender, who sends it from there. With ``send`` the recipient
        signs first: the document goes to the recipient right away."""
        self.ensure_one()
        if not recipient_edrpou and not recipient_emails:
            raise UserError(_('Give the ЄДРПОУ or the e-mail of the recipient.'))
        filename, content = self._edo_render(report)
        meta = self._edo_meta()
        category = category or account._category_for(report).code or meta.get('category')
        payload = dict(meta, filename=filename, content=content,
                       title=title or meta.get('title') or filename,
                       category=category,
                       recipient_edrpou=recipient_edrpou, recipient_emails=recipient_emails or [],
                       recipient_signs_first=bool(send))
        data = account._call('upload', payload)
        vals = account._call('normalize', data)
        if send:
            account._call('send', vals['provider_ref'])
        partner = self._edo_partner()
        doc = self.env['l10n_ua.edo.document'].create({
            **{k: v for k, v in vals.items() if k in self.env['l10n_ua.edo.document']._fields},
            'name': payload['title'],
            'account_id': account.id,
            'direction': 'out',
            'number': meta.get('number') or vals.get('number'),
            'date': meta.get('date') or vals.get('date'),
            'amount': meta.get('amount') or vals.get('amount') or 0.0,
            'counterparty_edrpou': recipient_edrpou,
            'counterparty_name': partner.name if partner else False,
            'partner_id': partner.id if partner else False,
            'res_model': self._name,
            'res_id': self.id,
            'last_sync': fields.Datetime.now(),
        })
        attachment = self.env['ir.attachment'].create({
            'name': filename, 'raw': content, 'res_model': doc._name, 'res_id': doc.id})
        doc.attachment_id = attachment
        if send:
            doc.action_refresh()
        if hasattr(self, 'message_post'):
            self.message_post(body=_('Sent to EDO: «%s».', payload['title']))
        return doc

    # ── Actions ─────────────────────────────────────────────

    def action_edo_send(self):
        """The send wizard for one record or for several (each to its own
        counterparty)."""
        if not self:
            raise UserError(_('Select the documents to send.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send to EDO'),
            'res_model': 'l10n_ua.edo.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self[:1].id,
                'default_res_ids': ','.join(str(i) for i in self.ids),
            },
        }

    def _edo_recipient(self):
        """(ЄДРПОУ, [e-mails]) of the counterparty from its card."""
        self.ensure_one()
        partner = self._edo_partner()
        if not partner:
            return False, []
        edrpou = partner['edrpou'] if 'edrpou' in partner._fields else False
        return edrpou or False, [partner.email] if partner.email else []

    def action_view_edo_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('EDO Documents'),
            'res_model': 'l10n_ua.edo.document', 'view_mode': 'list,form',
            'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
        }
