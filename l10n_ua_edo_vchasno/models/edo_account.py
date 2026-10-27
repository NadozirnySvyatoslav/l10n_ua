from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .vchasno_client import DEFAULT_BASE_URL, VchasnoClient, VchasnoError

# Statuses of Вчасно → states of l10n_ua.edo.document
VCHASNO_STATES = {
    7000: 'uploaded',      # завантажений у систему
    7001: 'uploaded',      # готовий для підпису й надсилання
    7002: 'sent',          # надісланий контрагенту на перший підпис
    7003: 'signing',       # підписаний не всіма підписами власника
    7004: 'signed_owner',  # підписаний власником, чекає на контрагента
    7006: 'rejected',      # відхилений контрагентом
    7007: 'signing',       # підписаний не всіма підписами отримувача
    7008: 'signed',        # накладено всі очікувані підписи
    7010: 'sent',          # надісланий підписантам (багатосторонній)
    7011: 'deleted',       # анульований
}


class L10nUaEdoAccount(models.Model):
    _inherit = 'l10n_ua.edo.account'

    provider = fields.Selection(selection_add=[('vchasno', 'Вчасно')], ondelete={'vchasno': 'set null'})

    def _vchasno_client(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_ua_edo_vchasno.base_url', DEFAULT_BASE_URL)
        return VchasnoClient(self._token(), base_url)

    def _vchasno(self, method, *args):
        try:
            return getattr(self._vchasno_client(), method)(*args)
        except VchasnoError as error:
            raise UserError(str(error)) from error

    def _vchasno_test(self):
        return _('The token works: %s document categories in Вчасно.', len(self._vchasno_categories()))

    def _vchasno_categories(self):
        data = self._vchasno('categories')
        if isinstance(data, dict):
            data = data.get('categories') or data.get('document_categories') or []
        return [(str(c['category_id']), c['category_title']) for c in data
                if c.get('category_id') not in (None, 0, '0') and c.get('is_public', True)]

    def _vchasno_default_categories(self):
        """Standard categories of Вчасно for the Ukrainian printed forms."""
        return {
            'l10n_ua_doc_reports.action_report_rahunok_invoice': '2',   # Рахунок
            'l10n_ua_doc_reports.action_report_rahunok_sale': '2',      # Рахунок
            'l10n_ua_doc_reports.action_report_act': '1',               # Акт наданих послуг
            'l10n_ua_doc_reports.action_report_vydatkova': '5',         # Видаткова накладна
            'l10n_ua_agreement.action_report_agreement': '3',           # Договір
            'l10n_ua_agreement.action_report_agreement_act': '1',       # Акт наданих послуг
        }

    def _vchasno_bill_categories(self):
        """Incoming documents of these categories become vendor bills; a contract does not."""
        return {'1', '2', '5'}  # Акт наданих послуг, Рахунок, Видаткова накладна

    def _vchasno_upload(self, payload):
        params = {
            'title': payload.get('title'),
            'doc_number': payload.get('number'),
            'date_document': payload['date'].isoformat() if payload.get('date') else None,
            'amount': int(round((payload.get('amount') or 0.0) * 100)) or None,
            'category': payload.get('category'),
            'recipient_edrpou': payload.get('recipient_edrpou'),
            'recipient_emails': list(payload.get('recipient_emails') or []) or None,
            'first_sign_by': 'recipient' if payload.get('recipient_signs_first') else None,
        }
        return self._vchasno('upload', payload['filename'], payload['content'], params)

    def _vchasno_send(self, ref):
        return self._vchasno('send', ref)

    def _vchasno_fetch(self, refs):
        return self._vchasno('documents', refs)

    def _vchasno_incoming(self, date_from):
        return self._vchasno('incoming', date_from)

    def _vchasno_download(self, ref, kind):
        return self._vchasno('download', ref, kind)

    def _vchasno_normalize(self, data):
        """Values of l10n_ua.edo.document from a document of Вчасно."""
        status = data.get('status')
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            status_code = None
        vals = {
            'provider_ref': str(data.get('id') or ''),
            'provider_status': str(status) if status is not None else False,
            'url': data.get('url') or False,
            'number': data.get('number') or data.get('doc_number') or False,
            'amount': (float(data['amount']) / 100.0) if data.get('amount') else 0.0,
            'category': str(data['category']) if data.get('category') is not None else False,
        }
        if data.get('title'):
            vals['name'] = data['title']
        date = data.get('date') or data.get('date_document') or data.get('date_created')
        if date:
            vals['date'] = str(date)[:10]
        if status_code in VCHASNO_STATES:
            vals['state'] = VCHASNO_STATES[status_code]
        # The owner is the counterparty only for a document the company did not upload
        owner = data.get('edrpou_owner')
        if owner and owner != self.edrpou:
            vals['counterparty_edrpou'] = owner
            vals['counterparty_name'] = data.get('company_name') or False
        return vals
