"""Провайдер ЕДО «Вчасно» з фальшивою HTTP-сесією (#81)."""

import base64
import json
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_ua_edo_vchasno.models import vchasno_client


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b'', headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content or (json.dumps(payload).encode() if payload is not None else b'')
        self.text = self.content.decode(errors='ignore')
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    """Answers by (method, path); records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        path = url.split('/api/v2', 1)[1]
        self.calls.append((method, path, headers, kwargs))
        answer = self.routes.get((method, path))
        if callable(answer):
            answer = answer(kwargs)
        return answer or FakeResponse(404, {'reason': 'not found'})


@tagged('post_install', '-at_install', 'l10n_ua_edo')
class TestVchasno(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.account = cls.env['l10n_ua.edo.account'].create({
            'name': 'Вчасно (тест)', 'provider': 'vchasno', 'token': 'test-token',
            'edrpou': '11111116', 'company_id': cls.company.id,
            'incoming_date_from': date(2026, 1, 1),
        })

    def _session(self, routes):
        session = FakeSession(routes)
        original = vchasno_client.VchasnoClient.__init__

        def init(client, token, base_url=vchasno_client.DEFAULT_BASE_URL, session_=None):
            original(client, token, base_url, session)
        self.patch(vchasno_client.VchasnoClient, '__init__', init)
        return session

    def test_upload_and_send(self):
        doc = {'id': 'abc-1', 'title': 'Акт № 7', 'status': 7000, 'url': 'https://vchasno.ua/app/documents/abc-1',
               'edrpou_owner': '11111116', 'amount': 1250050}
        session = self._session({
            ('POST', '/documents'): FakeResponse(201, {'documents': [doc]}),
            ('POST', '/documents/abc-1/send'): FakeResponse(200, {}),
        })
        data = self.account._call('upload', {
            'filename': 'act.pdf', 'content': b'%PDF-1.4', 'title': 'Акт № 7', 'number': '7',
            'date': date(2026, 10, 1), 'amount': 12500.5, 'recipient_edrpou': '22222221',
            'recipient_emails': ['buh@example.com'], 'recipient_signs_first': True})
        self.account._call('send', 'abc-1')
        method, path, headers, kwargs = session.calls[0]
        self.assertEqual(headers['Authorization'], 'test-token')
        self.assertEqual(kwargs['params']['amount'], 1250050)          # kopecks
        self.assertEqual(kwargs['params']['date_document'], '2026-10-01')
        self.assertEqual(kwargs['params']['first_sign_by'], 'recipient')
        self.assertEqual(kwargs['params']['recipient_emails'], ['buh@example.com'])   # repeated parameter
        self.assertIn('files', kwargs['files'])
        self.assertEqual(session.calls[1][1], '/documents/abc-1/send')
        vals = self.account._call('normalize', data)
        self.assertEqual((vals['provider_ref'], vals['state'], vals['amount']), ('abc-1', 'uploaded', 12500.5))
        self.assertNotIn('counterparty_edrpou', vals)                  # we are the owner

    def test_sync_updates_status_and_fetches_the_signed_archive(self):
        outgoing = self.env['l10n_ua.edo.document'].create({
            'name': 'Видаткова № 3', 'account_id': self.account.id, 'direction': 'out',
            'provider_ref': 'out-3', 'state': 'sent'})
        self._session({
            ('GET', '/documents'): FakeResponse(200, {'documents': [
                {'id': 'out-3', 'title': 'Видаткова № 3', 'status': 7008, 'edrpou_owner': '11111116'}]}),
            ('GET', '/documents/out-3/archive'): FakeResponse(
                200, content=b'PK..', headers={'Content-Disposition': 'attachment; filename="vydatkova_3.zip"'}),
            ('GET', '/incoming-documents'): FakeResponse(200, {'documents': [
                {'id': 'in-9', 'title': 'Рахунок № 45', 'status': 7002, 'edrpou_owner': '22222221',
                 'company_name': 'ТОВ «Постачальник»', 'number': '45', 'amount': 99900,
                 'date': '2026-10-20', 'date_created': '2026-10-21T09:15:00'}], 'next_cursor': None}),
        })
        self.account.action_sync()
        self.assertEqual(outgoing.state, 'signed')
        self.assertEqual(outgoing.archive_attachment_id.name, 'vydatkova_3.zip')
        incoming = self.env['l10n_ua.edo.document'].search([('provider_ref', '=', 'in-9')])
        self.assertEqual(incoming.direction, 'in')
        self.assertEqual((incoming.number, incoming.amount, str(incoming.date)), ('45', 999.0, '2026-10-20'))
        self.assertEqual(incoming.counterparty_edrpou, '22222221')
        self.assertTrue(self.account.last_sync)
        # A second synchronisation does not duplicate the incoming document
        self.account.action_sync()
        self.assertEqual(self.env['l10n_ua.edo.document'].search_count([('provider_ref', '=', 'in-9')]), 1)

    def test_incoming_partner_found_by_edrpou(self):
        Partner = self.env['res.partner']
        if 'edrpou' not in Partner._fields:
            self.skipTest('res.partner.edrpou needs l10n_ua_account_base')
        supplier = Partner.create({'name': 'ТОВ «Постачальник»', 'is_company': True, 'edrpou': '22222221'})
        self._session({
            ('GET', '/incoming-documents'): FakeResponse(200, {'documents': [
                {'id': 'in-1', 'title': 'Акт', 'status': 7002, 'edrpou_owner': '22222221'}]}),
        })
        self.account.action_sync()
        doc = self.env['l10n_ua.edo.document'].search([('provider_ref', '=', 'in-1')])
        self.assertEqual(doc.partner_id, supplier)

    def test_rejected_token_is_a_user_error(self):
        self._session({('GET', '/document-categories'): FakeResponse(401, {'reason': 'Unauthorized'})})
        with self.assertRaisesRegex(UserError, 'токен'):
            self.account.action_test_connection()

    def test_sync_error_is_kept_on_the_account(self):
        self._session({('GET', '/incoming-documents'): FakeResponse(500, {'reason': 'boom'})})
        self.env['l10n_ua.edo.account']._cron_sync()
        self.assertIn('500', self.account.last_error)

    def test_load_categories_and_rules(self):
        self._session({('GET', '/document-categories'): FakeResponse(200, [
            {'category_id': 0, 'category_title': 'Тип не обрано'},
            {'category_id': 1, 'category_title': 'Акт наданих послуг'},
            {'category_id': 2, 'category_title': 'Рахунок'},
            {'category_id': 3, 'category_title': 'Договір'},
            {'category_id': 5, 'category_title': 'Видаткова накладна'},
            {'category_id': 22, 'category_title': 'Акт повернення'},
            {'category_id': 37, 'category_title': 'Внутрішній тип', 'is_public': False},
        ])})
        self.account.action_load_categories()
        self.assertEqual(sorted(self.account.category_ids.mapped('code')), ['1', '2', '22', '3', '5'])  # not the internal 37
        rahunok = self.env.ref('l10n_ua_doc_reports.action_report_rahunok_invoice', raise_if_not_found=False)
        if rahunok:
            self.assertEqual(self.account._category_for(rahunok).name, 'Рахунок')
        # A second load neither duplicates the categories nor the rules
        rules = len(self.account.category_rule_ids)
        self.account.action_load_categories()
        self.assertEqual(len(self.account.category_ids), 5)
        self.assertEqual(len(self.account.category_rule_ids), rules)

    def test_lists_follow_next_cursor_and_repeat_ids(self):
        pages = {None: {'documents': [{'id': 'a', 'status': 7004}], 'next_cursor': 'c2'},
                 'c2': {'documents': [{'id': 'b', 'status': 7008}], 'next_cursor': None}}
        session = self._session({('GET', '/documents'): lambda kw: FakeResponse(200, pages[kw['params'].get('cursor')])})
        documents = self.account._call('fetch', ['a', 'b'])
        self.assertEqual([d['id'] for d in documents], ['a', 'b'])
        self.assertEqual(session.calls[0][3]['params']['ids'], ['a', 'b'])
        self.assertEqual(session.calls[1][3]['params']['cursor'], 'c2')

    def test_annulled_document(self):
        self.assertEqual(self.account._call('normalize', {'id': 'x', 'status': 7011})['state'], 'deleted')

    # ── КЕП signature, recognised data, defaults ────────────

    def _doc(self, ref, direction, status, **vals):
        return self.env['l10n_ua.edo.document'].create(dict({
            'name': f'Документ {ref}', 'account_id': self.account.id, 'direction': direction,
            'provider_ref': ref, 'provider_status': str(status)}, **vals))

    def test_whose_turn_to_sign(self):
        cases = [('out', 7001, True), ('out', 7003, True), ('out', 7002, False), ('out', 7004, False),
                 ('in', 7002, True), ('in', 7004, True), ('in', 7007, True), ('in', 7008, False),
                 ('in', 7001, False)]
        for index, (direction, status, expected) in enumerate(cases):
            doc = self._doc(f'turn-{index}', direction, status)
            self.assertEqual(doc.can_sign, expected, f'{direction} {status}')
            self.assertTrue(doc.can_extract)

    def test_sign_outgoing_with_kep_and_send(self):
        doc = self._doc('out-7', 'out', 7001, state='uploaded')
        doc.attachment_id = self.env['ir.attachment'].create({
            'name': 'act_7.pdf', 'raw': b'%PDF-1.4 act', 'res_model': doc._name, 'res_id': doc.id})
        session = self._session({
            ('GET', '/documents'): FakeResponse(200, {'documents': [
                {'id': 'out-7', 'status': 7004, 'edrpou_owner': '11111116'}]}),
            ('POST', '/documents/out-7/signatures'): FakeResponse(201, {}),
            ('POST', '/documents/out-7/send'): FakeResponse(200, {}),
        })
        prepared = doc.kep_prepare_signing()
        [document] = prepared['documents']
        self.assertEqual(document['format'], 'cades_detached')       # Вчасно takes a detached p7s
        self.assertEqual(base64.b64decode(document['data_b64']), b'%PDF-1.4 act')
        result = doc.kep_submit_signed({'document': 'U0lHTg=='})
        calls = [(method, path) for method, path, _h, _k in session.calls]
        self.assertEqual(calls[:2], [('POST', '/documents/out-7/signatures'), ('POST', '/documents/out-7/send')])
        self.assertEqual(session.calls[0][3]['json'], {'signature': 'U0lHTg=='})
        self.assertEqual(doc.state, 'signed_owner')
        self.assertIn('sent', result['receipt'])

    def test_sign_incoming_is_not_sent_again(self):
        doc = self._doc('in-7', 'in', 7004, state='signed_owner')
        session = self._session({
            ('GET', '/documents/in-7/original'): FakeResponse(
                200, content=b'%PDF in', headers={'Content-Disposition': 'attachment; filename="in.pdf"'}),
            ('GET', '/documents'): FakeResponse(200, {'documents': [{'id': 'in-7', 'status': 7008}]}),
            ('GET', '/documents/in-7/archive'): FakeResponse(200, content=b'PK..'),
            ('POST', '/documents/in-7/signatures'): FakeResponse(201, {}),
        })
        prepared = doc.kep_prepare_signing()
        self.assertEqual(doc.attachment_id.name, 'in.pdf')            # the original, fetched once
        self.assertEqual(base64.b64decode(prepared['documents'][0]['data_b64']), b'%PDF in')
        doc.kep_submit_signed({'document': 'U0lHTg=='})
        self.assertNotIn(('POST', '/documents/in-7/send'), [(m, p) for m, p, _h, _k in session.calls])
        self.assertEqual(doc.state, 'signed')

    def test_sign_refused_when_not_our_turn(self):
        doc = self._doc('out-8', 'out', 7004)
        with self.assertRaises(UserError):
            doc.action_edo_sign()

    def test_recognised_data(self):
        session = self._session({
            ('GET', '/documents/ready/structured-data/download'): FakeResponse(200, {
                'items': [{'name': 'Консультація', 'quantity': 2, 'price_with_vat': 500}],
                'total_price': {'total_price_with_vat': 1000}}),
            ('GET', '/documents/wait/structured-data/download'): FakeResponse(200, {
                'document_id': 'wait', 'status': 'awaiting_validation'}),
            ('POST', '/documents/structured-data/extractions'): FakeResponse(200, {'data': [
                {'document_id': 'wait', 'status': 'pending'}]}),
        })
        self.assertEqual(self.account._call('structured_data', 'ready')['items'][0]['quantity'], 2)
        self.assertIsNone(self.account._call('structured_data', 'wait'))
        self.assertEqual(self.account._call('extract', ['wait'])[0]['status'], 'pending')
        self.assertEqual(session.calls[-1][3]['json'], {'document_ids': ['wait']})
        vals = self.account._vchasno_normalize({'id': 'x', 'status': 7002, 'sd_status': 'confirmed'})
        self.assertEqual(vals['data_state'], 'confirmed')

    def test_new_account_imports_from_the_start_of_the_year(self):
        account = self.env['l10n_ua.edo.account'].create({'name': 'Новий', 'company_id': self.company.id})
        self.assertEqual((account.incoming_date_from.month, account.incoming_date_from.day), (1, 1))
