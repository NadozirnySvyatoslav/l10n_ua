import base64
import hashlib
import io
import logging
import os
import uuid
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import email_split

from .kep_cms import KepSignatureError, embedded_content, parse_signature

_logger = logging.getLogger(__name__)

SIGNATURE_EXTENSIONS = ('.p7s', '.p7m', '.sig')
# Files of an archive of an EDO service that are not the document
SERVICE_FILES = ('kvytantsiia', 'instruktsiia', 'квитанц', 'квітанц', 'інструкц', 'receipt', 'instruction')
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_ZIP_FILES = 50


def _base(filename):
    return os.path.splitext(filename or '')[0]


class L10nUaEdoDocument(models.Model):
    _name = 'l10n_ua.edo.document'
    _inherit = ['l10n_ua.edo.document', 'portal.mixin']

    kep_signature_ids = fields.One2many(
        'l10n_ua.edo.kep.signature', 'document_id', string='КЕП Signatures', readonly=True)
    kep_recipient_emails = fields.Char(
        string='Counterparty E-mails',
        help='Where the document goes: the invitation to sign, the signed archive. '
             'For a document received by e-mail — its sender.')
    kep_invited = fields.Boolean(string='Invitation Sent', readonly=True, copy=False)
    kep_rejected = fields.Boolean(string='Rejected', readonly=True, copy=False)
    kep_reject_reason = fields.Text(string='Reason of Rejection', readonly=True, copy=False)
    kep_unchecked_count = fields.Integer(compute='_compute_kep_checks')
    kep_invalid_count = fields.Integer(compute='_compute_kep_checks')
    kep_can_sign_their = fields.Boolean(compute='_compute_kep_checks')

    @api.depends('kep_signature_ids.verification')
    def _compute_kep_checks(self):
        for doc in self:
            signatures = doc.kep_signature_ids
            doc.kep_unchecked_count = len(signatures.filtered(lambda s: s.verification == 'pending'))
            doc.kep_invalid_count = len(signatures.filtered(lambda s: s.verification == 'invalid'))
            doc.kep_can_sign_their = doc._kep_can_sign_their()

    def _compute_access_url(self):
        super()._compute_access_url()
        for doc in self:
            doc.access_url = f'/my/edo/{doc.id}'

    # ── Parties and state ───────────────────────────────────

    def _is_kep(self):
        self.ensure_one()
        return self.account_id.provider == 'kep'

    def _kep_own_party(self):
        """The company is the sender of an outgoing document, the recipient of an incoming one."""
        self.ensure_one()
        return 'owner' if self.direction == 'out' else 'recipient'

    def _kep_their_party(self):
        self.ensure_one()
        return 'recipient' if self.direction == 'out' else 'owner'

    def _kep_signatures(self, party):
        self.ensure_one()
        return self.kep_signature_ids.filtered(lambda s: s.party == party and s.verification != 'invalid')

    def _kep_state(self):
        self.ensure_one()
        if self.kep_rejected:
            return 'rejected'
        owner = bool(self._kep_signatures('owner'))
        recipient = bool(self._kep_signatures('recipient'))
        if owner and recipient:
            return 'signed'
        if owner:
            return 'signed_owner'
        if recipient:
            return 'signing'
        return 'sent' if self.kep_invited or self.direction == 'in' else 'uploaded'

    def _kep_data(self):
        """The document as the provider «lists» it (see ``_kep_normalize``)."""
        self.ensure_one()
        return {'id': self.provider_ref, 'state': self._kep_state(),
                'url': self.get_base_url() + self.get_portal_url()}

    def _kep_open(self):
        self.ensure_one()
        return self.state not in ('rejected', 'deleted')

    def _kep_can_sign_own(self):
        self.ensure_one()
        return bool(self._is_kep() and self._kep_open() and self.attachment_id
                    and not self._kep_signatures(self._kep_own_party()))

    def _kep_can_sign_their(self):
        """The counterparty signs on the portal: an outgoing document it has not signed yet."""
        self.ensure_one()
        return bool(self.account_id.provider == 'kep' and self.direction == 'out' and self._kep_open()
                    and self.attachment_id and not self._kep_signatures(self._kep_their_party()))

    def _kep_refresh(self):
        self.ensure_one()
        self._apply_provider_vals(self.account_id._kep_normalize(self._kep_data()))

    # ── Signatures ──────────────────────────────────────────

    def _kep_add_signature(self, data, filename=None, expect=None, attached=False):
        """Add a signature of the document; whose it is comes from its certificate.

        :param bytes data: the .p7s (detached, or with the data when ``attached``)
        :param str expect: 'own' — must be the company's (signed in Odoo);
            'their' — must be the counterparty's (signed on the portal)
        :return: the signature, or an empty recordset for one already there
        """
        self.ensure_one()
        try:
            info = parse_signature(data, attached=attached)
            content = embedded_content(data) if attached else None
        except KepSignatureError as error:
            raise UserError(_('This is not a КЕП signature of the document: %s', error)) from error
        if attached and self.attachment_id and content != self.attachment_id.raw:
            raise UserError(_('The signature is of another file, not of «%s».', self.attachment_id.name))
        codes = {c for c in (info['edrpou'], info['drfo']) if c}
        own = bool(codes & self.account_id._own_codes())
        who = info['organization'] or info['signer_name']
        if expect == 'own' and not own:
            raise UserError(_(
                'The key belongs to %(who)s (%(codes)s), not to the company (%(company)s).',
                who=who, codes=', '.join(sorted(codes)) or '—',
                company=', '.join(sorted(self.account_id._own_codes())) or '—'))
        if expect == 'their' and own:
            raise UserError(_('This link is for the counterparty: the company signs the document in Odoo.'))
        if not own:
            if self.counterparty_edrpou and self.counterparty_edrpou not in codes:
                raise UserError(_(
                    'The key belongs to %(who)s (%(codes)s), not to the counterparty of the document '
                    '(ЄДРПОУ %(edrpou)s).', who=who, codes=', '.join(sorted(codes)) or '—',
                    edrpou=self.counterparty_edrpou))
            if not self.counterparty_edrpou:
                code = info['edrpou'] or info['drfo']
                partner = self.partner_id or self._find_partner(code)
                self.write({
                    'counterparty_edrpou': code,
                    'counterparty_name': info['organization'] or info['signer_name'],
                    'partner_id': partner.id or False,
                })
        party = self._kep_own_party() if own else self._kep_their_party()
        Signature = self.env['l10n_ua.edo.kep.signature']
        if self.kep_signature_ids.filtered(
                lambda s: s.party == party and s.cert_serial == info['cert_serial'] and s.verification != 'invalid'):
            return Signature
        signature = Signature.create({
            **info,
            'document_id': self.id,
            'party': party,
            'attached': attached,
            'signing_time': info['signing_time'] or fields.Datetime.now(),
            'attachment_id': self.env['ir.attachment'].create({
                'name': filename or 'signature.p7s', 'raw': data,
                'res_model': self._name, 'res_id': self.id,
                'mimetype': 'application/pkcs7-signature',
            }).id,
        })
        signature.attachment_id.name = signature._filename(_base(self.attachment_id.name) or self.name)
        if self.state == 'signed':
            self._kep_rebuild_archive()  # one more signature (a seal) after all signed
        self._kep_refresh()
        return signature

    def _kep_add_signature_b64(self, signature_b64, expect=None):
        return self._kep_add_signature(base64.b64decode(signature_b64), expect=expect)

    # ── Archive ─────────────────────────────────────────────

    def _kep_archive(self):
        """(filename, zip): the original, a .p7s per signature, the receipt."""
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_('Document «%s» has no original file.', self.name))
        original = self.attachment_id
        base = _base(original.name) or self.name
        buffer = io.BytesIO()
        names = set()

        def unique(name):
            stem, ext = os.path.splitext(name)
            candidate, n = name, 1
            while candidate in names:
                n += 1
                candidate = f'{stem} ({n}){ext}'
            names.add(candidate)
            return candidate

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(unique(original.name), original.raw)
            for signature in self.kep_signature_ids.filtered(lambda s: s.verification != 'invalid'):
                archive.writestr(unique(signature._filename(base)), signature.attachment_id.raw)
            archive.writestr(unique('Kvytantsiia.pdf'), self._kep_receipt_pdf())
        return f'{base}.zip', buffer.getvalue()

    def _kep_receipt_pdf(self):
        self.ensure_one()
        report = self.env.ref('l10n_ua_edo_kep.action_report_kep_receipt')
        content, _type = self.env['ir.actions.report'].sudo().with_company(self.company_id) \
            ._render_qweb_pdf(report, self.ids)
        return content

    def _kep_rebuild_archive(self):
        self.ensure_one()
        old = self.archive_attachment_id
        self._fetch_file('archive')
        if old and old.res_model == self._name and old.res_id == self.id:
            old.unlink()

    def _kep_original_sha256(self):
        self.ensure_one()
        return hashlib.sha256(self.attachment_id.raw or b'').hexdigest() if self.attachment_id else ''

    # ── Delivery by e-mail ──────────────────────────────────

    def _kep_emails(self):
        self.ensure_one()
        return [e.strip() for e in (self.kep_recipient_emails or '').replace(';', ',').split(',') if e.strip()]

    def _kep_deliver(self):
        """Send the document on: an invitation to sign it on the portal while the
        counterparty has not signed an outgoing one, else the archive with the
        signatures."""
        self.ensure_one()
        if not self._kep_emails():
            raise UserError(_('Give the e-mail of the counterparty of «%s» to send it.', self.name))
        if self.state == 'rejected':
            return
        if self.direction == 'out' and not self._kep_signatures(self._kep_their_party()):
            template = self.env.ref('l10n_ua_edo_kep.mail_template_kep_invitation')
            self._kep_send_mail(template)
            self.kep_invited = True
            self._kep_refresh()
            self.message_post(body=_('Invitation to sign sent to %s.', self.kep_recipient_emails))
        else:
            if not self.archive_attachment_id or self.state != 'signed':
                self._kep_rebuild_archive()
            template = self.env.ref('l10n_ua_edo_kep.mail_template_kep_signed')
            self._kep_send_mail(template, attachments=self.archive_attachment_id)
            self.message_post(body=_('The archive with the signatures sent to %s.', self.kep_recipient_emails))

    def _kep_send_mail(self, template, attachments=None):
        self.ensure_one()
        partner = self.partner_id
        lang = (partner.lang if partner else False) or self.env.lang
        template.with_context(lang=lang).send_mail(
            self.id, force_send=False, raise_exception=True,
            email_values={'email_to': ', '.join(self._kep_emails()),
                          'recipient_ids': [],
                          'attachment_ids': attachments.ids if attachments else []})

    # ── Rejection ───────────────────────────────────────────

    def _kep_reject(self, reason, by_counterparty):
        self.ensure_one()
        if not self._kep_open():
            raise UserError(_('Document «%s» is already closed.', self.name))
        self.write({'kep_rejected': True, 'kep_reject_reason': reason or False})
        self._kep_refresh()
        if by_counterparty:
            self.message_post(body=_('Rejected by the counterparty: %s', reason or '—'),
                              subtype_xmlid='mail.mt_comment')
        elif self._kep_emails():
            self._kep_send_mail(self.env.ref('l10n_ua_edo_kep.mail_template_kep_rejected'))
            self.message_post(body=_('Rejected: %s. The counterparty is told.', reason or '—'))

    # ── Portal ──────────────────────────────────────────────

    def _kep_portal_sign(self, signature_b64):
        """The counterparty's signature from the portal."""
        self.ensure_one()
        if not self._kep_can_sign_their():
            raise UserError(_('The document is not waiting for your signature.'))
        signature = self._kep_add_signature_b64(signature_b64, expect='their')
        self.message_post(
            body=_('Signed by %s on the portal. Check the signature in Odoo.',
                   signature.signer_name if signature else self.counterparty_name),
            subtype_xmlid='mail.mt_comment')
        if self.state == 'signed':
            self._kep_deliver()
        return signature

    def kep_prepare_signing(self):
        spec = super().kep_prepare_signing()
        if self._is_kep():
            if self.direction == 'out':
                spec['description'] = _('The signature stays in Odoo; the counterparty then gets a link '
                                        'to sign the document with its КЕП.')
            else:
                spec['description'] = _('The signature stays in Odoo; the archive with the signatures '
                                        'goes back to the sender.')
        return spec

    # ── Check of the signatures (in the browser of an Odoo user) ──

    def action_kep_verify(self):
        self.ensure_one()
        if not self.kep_signature_ids:
            raise UserError(_('The document has no signatures yet.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'l10n_ua_edo_kep.verify',
            'params': {'res_id': self.id},
        }

    def kep_verification_data(self):
        self.ensure_one()
        return {
            'data_b64': self.attachment_id.datas.decode() if self.attachment_id else '',
            'signatures': [{
                'id': s.id, 'sign_b64': s.attachment_id.datas.decode(), 'attached': s.attached,
                'signer': s.signer_name,
            } for s in self.kep_signature_ids],
        }

    def kep_store_verification(self, results):
        """Results of the check in the browser: [{id, valid, error, owner}]."""
        self.ensure_one()
        by_id = {s.id: s for s in self.kep_signature_ids}
        valid = invalid = 0
        for result in results or []:
            signature = by_id.get(result.get('id'))
            if not signature:
                continue
            ok = bool(result.get('valid'))
            signature.write({
                'verification': 'valid' if ok else 'invalid',
                'verified_on': fields.Datetime.now(),
                'verification_error': False if ok else (result.get('error') or '')[:250],
            })
            valid += ok
            invalid += not ok
        self._kep_refresh()
        if self.state == 'signed':
            self._kep_rebuild_archive()
        self.message_post(body=_('Signatures checked: %(valid)s valid, %(invalid)s invalid.',
                                 valid=valid, invalid=invalid))
        return {'valid': valid, 'invalid': invalid}

    # ── Actions ─────────────────────────────────────────────

    def action_kep_send_again(self):
        for doc in self:
            doc._kep_deliver()
        return True

    def action_kep_reject(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Reject the Document'),
            'res_model': 'l10n_ua.edo.kep.reject.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_document_id': self.id},
        }

    def action_open_in_service(self):
        if len(self) == 1 and self._is_kep():
            return {'type': 'ir.actions.act_url', 'url': self.get_portal_url(), 'target': 'new'}
        return super().action_open_in_service()

    # ── Incoming by e-mail ──────────────────────────────────

    @api.model
    def _kep_unpack(self, attachments):
        """Split the files of a message: originals, detached and attached signatures.

        :param attachments: [(name, bytes)]
        :return: (originals, detached, attached) — lists of (name, bytes)
        """
        originals, detached, attached = [], [], []

        def walk(name, content, depth=0):
            lower = (name or '').lower()
            if lower.endswith('.zip') and depth < 2:
                try:
                    archive = zipfile.ZipFile(io.BytesIO(content))
                    members = [m for m in archive.infolist() if not m.is_dir()][:MAX_ZIP_FILES]
                    if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
                        _logger.warning('EDO КЕП: archive %s is too large, skipped', name)
                        return
                    for member in members:
                        walk(os.path.basename(member.filename), archive.read(member), depth + 1)
                except zipfile.BadZipFile:
                    originals.append((name, content))
                return
            if lower.endswith(SIGNATURE_EXTENSIONS):
                try:
                    data = embedded_content(content)
                except KepSignatureError:
                    return  # not a signature after all
                (attached if data else detached).append((name, content))
                return
            if any(word in lower for word in SERVICE_FILES):
                return
            originals.append((name, content))

        for name, content in attachments:
            if isinstance(content, str):
                content = content.encode()
            walk(name, content)
        return originals, detached, attached

    @api.model
    def _kep_match(self, originals, detached, attached):
        """[(original name, original bytes, [(sig name, bytes, attached)])] — a
        document per original that has signatures (or the only original)."""
        documents = []
        for name, content in attached:
            data = embedded_content(content)
            documents.append([_base(name) if name.lower().endswith(SIGNATURE_EXTENSIONS) else name,
                              data, [(name, content, True)]])
        if detached:
            if len(originals) == 1:
                documents.append([originals[0][0], originals[0][1], [(n, c, False) for n, c in detached]])
            else:
                for name, content in originals:
                    base = _base(name).lower()
                    mine = [(n, c, False) for n, c in detached if n.lower().startswith(base)]
                    if mine:
                        documents.append([name, content, mine])
        elif not attached and len(originals) == 1:
            documents.append([originals[0][0], originals[0][1], []])
        return documents

    def _kep_import_signatures(self, signatures):
        """Add signatures that came by e-mail; a broken one is noted, not fatal."""
        self.ensure_one()
        added = self.env['l10n_ua.edo.kep.signature']
        for name, content, is_attached in signatures:
            try:
                with self.env.cr.savepoint():
                    added |= self._kep_add_signature(content, filename=name, attached=is_attached)
            except UserError as error:
                self.message_post(body=_('Signature %(name)s not taken: %(error)s',
                                         name=name, error=error.args[0]))
        return added

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        values = dict(custom_values or {})
        account = self.env['l10n_ua.edo.account'].browse(values.get('account_id')).exists()
        if not account or account.provider != 'kep':
            return super().message_new(msg_dict, custom_values)
        files = [(a.fname, a.content) for a in msg_dict.get('attachments') or []
                 if not (a.info or {}).get('cid')]
        documents = self._kep_match(*self._kep_unpack(files))
        subject = (msg_dict.get('subject') or '').strip()
        sender = msg_dict.get('email_from') or ''
        first = None
        for filename, content, signatures in documents or [[None, None, []]]:
            doc = super().message_new(msg_dict, dict(
                values, direction='in', account_id=account.id,
                name=_base(filename) if filename else (subject or _('Document by e-mail')),
                provider_ref=str(uuid.uuid4()),
                kep_recipient_emails=', '.join(email_split(sender)) or False,
                date=fields.Date.context_today(self),
                state='sent',
            ))
            if filename:
                doc.attachment_id = self.env['ir.attachment'].create({
                    'name': filename, 'raw': content, 'res_model': doc._name, 'res_id': doc.id})
                doc._kep_import_signatures(signatures)
                doc._kep_refresh()
            else:
                doc.message_post(body=_('No document with a КЕП signature found in the message.'))
            if first is None:
                first = doc
            else:
                doc.message_post(body=_('Came in the same message as «%s».', first.name))
        return first

    def message_update(self, msg_dict, update_vals=None):
        result = super().message_update(msg_dict, update_vals)
        for doc in self.filtered(lambda d: d.account_id.provider == 'kep' and d.attachment_id):
            files = [(a.fname, a.content) for a in msg_dict.get('attachments') or []
                     if not (a.info or {}).get('cid')]
            originals, detached, attached = self._kep_unpack(files)
            signatures = [(n, c, False) for n, c in detached] + [(n, c, True) for n, c in attached]
            if signatures and doc._kep_import_signatures(signatures) and doc.state == 'signed' \
                    and doc.direction == 'out':
                doc.message_post(body=_('The counterparty signed by e-mail. Check the signature.'),
                                 subtype_xmlid='mail.mt_comment')
        return result
