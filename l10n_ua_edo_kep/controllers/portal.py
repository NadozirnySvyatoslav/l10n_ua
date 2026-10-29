"""Portal of a document exchanged with КЕП: the counterparty sees it, signs it
with its own КЕП in the browser, or rejects it. Access by the token of the link."""

import base64

from werkzeug.exceptions import Forbidden, NotFound

from odoo import _, http
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.l10n_ua_sign.controllers.ca_proxy import forward_ca_request
from odoo.addons.portal.controllers.portal import CustomerPortal


class EdoKepPortal(CustomerPortal):

    def _kep_document(self, doc_id, access_token):
        try:
            doc = self._document_check_access('l10n_ua.edo.document', doc_id, access_token)
        except (AccessError, MissingError):
            raise NotFound()
        if doc.account_id.provider != 'kep':
            raise NotFound()
        return doc

    @http.route('/my/edo/<int:doc_id>', type='http', auth='public', website=True)
    def portal_kep_document(self, doc_id, access_token=None, **kw):
        doc = self._kep_document(doc_id, access_token)
        token = access_token or doc._portal_ensure_token()
        values = {
            'doc': doc,
            'access_token': token,
            'page_name': 'edo_document',
            'can_sign': doc._kep_can_sign_their(),
            'signatures': doc.kep_signature_ids.filtered(lambda s: s.verification != 'invalid'),
            'proxy_url': f'/l10n_ua_edo_kep/ca_proxy/{doc.id}/{token}',
            'is_pdf': (doc.attachment_id.mimetype or '') == 'application/pdf',
        }
        return request.render('l10n_ua_edo_kep.portal_kep_document', values)

    @http.route('/my/edo/<int:doc_id>/file/<string:kind>', type='http', auth='public', website=True)
    def portal_kep_file(self, doc_id, kind, access_token=None, download=False, **kw):
        doc = self._kep_document(doc_id, access_token)
        if kind == 'archive':
            name, content = doc._kep_archive()
            mimetype = 'application/zip'
        elif kind == 'original' and doc.attachment_id:
            name, content = doc.attachment_id.name, doc.attachment_id.raw
            mimetype = doc.attachment_id.mimetype or 'application/octet-stream'
        else:
            raise NotFound()
        disposition = 'attachment' if download or kind == 'archive' else 'inline'
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', http.content_disposition(name, disposition_type=disposition)),
            ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/my/edo/<int:doc_id>/kep/prepare', type='jsonrpc', auth='public')
    def portal_kep_prepare(self, doc_id, access_token=None):
        doc = self._kep_document(doc_id, access_token)
        if not doc._kep_can_sign_their():
            return {'error': _('The document is not waiting for your signature.')}
        return {'data_b64': base64.b64encode(doc.attachment_id.raw).decode(),
                'filename': doc.attachment_id.name}

    @http.route('/my/edo/<int:doc_id>/kep/sign', type='jsonrpc', auth='public')
    def portal_kep_sign(self, doc_id, signature=None, access_token=None):
        doc = self._kep_document(doc_id, access_token)
        try:
            doc._kep_portal_sign(signature)
        except UserError as error:
            request.env.cr.rollback()
            return {'error': error.args[0]}
        return {'ok': True}

    @http.route('/my/edo/<int:doc_id>/kep/reject', type='jsonrpc', auth='public')
    def portal_kep_reject(self, doc_id, reason=None, access_token=None):
        doc = self._kep_document(doc_id, access_token)
        if not doc._kep_can_sign_their():
            return {'error': _('The document is not waiting for your signature.')}
        if not (reason or '').strip():
            return {'error': _('Give the reason.')}
        doc._kep_reject(reason.strip(), by_counterparty=True)
        return {'ok': True}

    @http.route('/l10n_ua_edo_kep/ca_proxy/<int:doc_id>/<string:token>', type='http', auth='public',
                methods=['GET', 'POST'], csrf=False)
    def portal_kep_ca_proxy(self, doc_id, token, address='', contentType='', **kw):
        """The CA proxy of the IIT library for the counterparty, who has no Odoo user:
        only with the token of a КЕП document that waits for its signature."""
        doc = request.env['l10n_ua.edo.document'].sudo().browse(doc_id).exists()
        if not doc or not doc.access_token or not consteq(doc.access_token, token) \
                or doc.account_id.provider != 'kep' or not doc._kep_can_sign_their():
            raise Forbidden()
        return forward_ca_request(address, contentType)
