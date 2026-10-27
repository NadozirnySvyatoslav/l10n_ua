"""Провайдер ЕДО «Вчасно» з фальшивою HTTP-сесією (#81)."""

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
