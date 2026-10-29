"""Provider «КЕП»: document exchange without an EDO service.

The operations of ``l10n_ua.edo.account`` work on the documents in Odoo itself:
the document is signed with КЕП in the browser (``l10n_ua_sign``), the
counterparty gets a link to the portal, where it signs with its own КЕП, or
answers by e-mail; the archive with the signatures is built here. Incoming
documents come by e-mail to the alias of the account.
"""

import uuid

from odoo import fields, models, _
from odoo.exceptions import UserError

KEP_CATEGORIES = [
    ('act', 'Акт'),
    ('invoice', 'Рахунок'),
    ('waybill', 'Видаткова накладна'),
    ('contract', 'Договір'),
    ('other', 'Інший документ'),
]


class L10nUaEdoAccount(models.Model):
    _name = 'l10n_ua.edo.account'
    _inherit = ['l10n_ua.edo.account', 'mail.alias.mixin.optional']

    provider = fields.Selection(selection_add=[('kep', 'КЕП (без сервісу ЕДО)')],
                                ondelete={'kep': 'set null'})

    # ── Alias: incoming documents by e-mail ─────────────────

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values['alias_model_id'] = self.env['ir.model']._get_id('l10n_ua.edo.document')
        if self.id:
            values['alias_defaults'] = repr({'account_id': self.id, 'direction': 'in'})
        return values

    # ── Operations ──────────────────────────────────────────

    def _kep_doc(self, ref):
        self.ensure_one()
        doc = self.env['l10n_ua.edo.document'].search(
            [('account_id', '=', self.id), ('provider_ref', '=', ref)], limit=1)
        if not doc:
            raise UserError(_('No КЕП document %s in this account.', ref))
        return doc

    def _kep_test(self):
        if self.alias_email:
            return _('Exchange with КЕП: no service and no token. Incoming documents: %s.',
                     self.alias_email)
        return _('Exchange with КЕП: no service and no token. Give the account an e-mail alias '
                 'to receive the documents of the counterparties.')

    def _kep_categories(self):
        return KEP_CATEGORIES

    def _kep_default_categories(self):
        return {
            'l10n_ua_doc_reports.action_report_rahunok_invoice': 'invoice',
            'l10n_ua_doc_reports.action_report_rahunok_sale': 'invoice',
            'l10n_ua_doc_reports.action_report_act': 'act',
            'l10n_ua_doc_reports.action_report_vydatkova': 'waybill',
            'l10n_ua_agreement.action_report_agreement': 'contract',
            'l10n_ua_agreement.action_report_agreement_act': 'act',
        }

    def _kep_bill_categories(self):
        return {'act', 'invoice', 'waybill'}

    def _kep_upload(self, payload):
        """Nothing leaves Odoo: the document only gets its id."""
        return {
            'id': str(uuid.uuid4()),
            'state': 'uploaded',
            'recipient_emails': list(payload.get('recipient_emails') or []),
            'category': payload.get('category'),
        }

    def _kep_send(self, ref):
        self._kep_doc(ref)._kep_deliver()

    def _kep_fetch(self, refs):
        docs = self.env['l10n_ua.edo.document'].search(
            [('account_id', '=', self.id), ('provider_ref', 'in', list(refs))])
        return [doc._kep_data() for doc in docs]

    def _kep_incoming(self, date_from):
        return []  # incoming documents come by e-mail (message_new)

    def _kep_download(self, ref, kind):
        doc = self._kep_doc(ref)
        if kind == 'archive':
            return doc._kep_archive()
        if not doc.attachment_id:
            raise UserError(_('Document «%s» has no original file.', doc.name))
        return doc.attachment_id.name, doc.attachment_id.raw

    def _kep_can_sign(self, doc):
        return doc._kep_can_sign_own()

    def _kep_sign(self, ref, signature_b64):
        doc = self._kep_doc(ref)
        doc._kep_add_signature_b64(signature_b64, expect='own')
        if doc.direction == 'in':
            doc._kep_deliver()  # our signature goes back to the sender

    def _kep_normalize(self, data):
        vals = {
            'provider_ref': data['id'],
            'provider_status': data.get('state') or False,
        }
        if data.get('state'):
            vals['state'] = data['state']
        if data.get('url'):
            vals['url'] = data['url']
        if data.get('recipient_emails') is not None:
            vals['kep_recipient_emails'] = ', '.join(data['recipient_emails']) or False
        if data.get('category'):
            vals['category'] = data['category']
        return vals

    def _own_codes(self):
        """ЄДРПОУ / РНОКПП a signature of the company carries (РНОКПП of a ФОП)."""
        self.ensure_one()
        codes = {self.edrpou}
        if 'edrpou' in self.company_id._fields:
            codes.add(self.company_id.edrpou)
        return {c.strip() for c in codes if c and c.strip()}
