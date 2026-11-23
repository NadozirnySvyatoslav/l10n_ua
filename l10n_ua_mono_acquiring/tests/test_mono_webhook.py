"""Webhook Monobank Acquiring: перевірка підпису X-Sign (без мережі)."""

import base64
import json
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from odoo.tests import HttpCase, tagged

from odoo.addons.l10n_ua_mono_acquiring.models import account_journal as aj

WEBHOOK = '/l10n_ua_mono_acquiring/webhook'


def _keypair():
    priv = ec.generate_private_key(ec.SECP256K1())
    pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv, pem


def _sign(priv, body):
    return base64.b64encode(priv.sign(body, ec.ECDSA(hashes.SHA256()))).decode()


@tagged('post_install', '-at_install')
class TestMonoWebhook(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.priv, cls.pem = _keypair()
        cls.journal = cls.env['account.journal'].create({
            'name': 'Mono WH', 'type': 'bank', 'code': 'MOWH',
            'company_id': cls.env.company.id,
            'mono_acquiring_token': 'wh-token'})
        partner = cls.env['res.partner'].create({'name': 'Клієнт WH'})
        cls.move = cls.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Послуга', 'quantity': 1, 'price_unit': 100.0})]})
        cls.move.action_post()
        cls.move.mono_invoice_id = 'inv-wh-1'

    def setUp(self):
        super().setUp()
        aj._MONO_PUBKEY_CACHE.clear()
        self.fetch = self.startPatcher(patch.object(
            aj.AccountJournal, '_mono_fetch_pubkey',
            autospec=True, return_value=self.pem))
        self.addCleanup(aj._MONO_PUBKEY_CACHE.clear)

    def _post(self, body, sign=None):
        headers = {'Content-Type': 'application/json'}
        if sign is not None:
            headers['X-Sign'] = sign
        return self.url_open(WEBHOOK, data=body, headers=headers)

    def _body(self, status='success', invoice_id='inv-wh-1'):
        return json.dumps({
            'invoiceId': invoice_id, 'status': status,
            'amount': 10000, 'ccy': 980}).encode()

    # --- HTTP ---

    def test_no_signature_rejected(self):
        resp = self._post(self._body())
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(self.move.payment_state, 'paid')

    def test_foreign_key_rejected(self):
        other_priv, _pem = _keypair()
        body = self._body()
        resp = self._post(body, _sign(other_priv, body))
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(self.move.payment_state, 'paid')

    def test_tampered_body_rejected(self):
        signed = self._body(status='processing')
        resp = self._post(self._body(), _sign(self.priv, signed))
        self.assertEqual(resp.status_code, 403)
        self.assertNotEqual(self.move.payment_state, 'paid')

    def test_valid_signature_registers_payment(self):
        body = self._body()
        resp = self._post(body, _sign(self.priv, body))
        self.assertEqual(resp.status_code, 200)
        self.move.invalidate_recordset(['payment_state'])
        self.assertIn(self.move.payment_state, ('paid', 'in_payment'))

    def test_valid_signature_not_success_no_payment(self):
        body = self._body(status='processing')
        resp = self._post(body, _sign(self.priv, body))
        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(self.move.payment_state, 'paid')

    def test_unknown_invoice_ack(self):
        resp = self._post(self._body(invoice_id='nope'), 'x')
        self.assertEqual(resp.status_code, 200)

    def test_malformed_json(self):
        resp = self._post(b'{not json', 'x')
        self.assertEqual(resp.status_code, 400)

    # --- Ключ ---

    def test_key_rotation_refetch(self):
        new_priv, new_pem = _keypair()
        body = self._body()
        sign = _sign(new_priv, body)
        # У кеші старий ключ, отриманий давно: дозволено запитати новий.
        aj._MONO_PUBKEY_CACHE[self.journal._mono_cache_key()] = (
            self.pem, -10 ** 6)
        self.fetch.return_value = new_pem
        self.assertTrue(self.journal._mono_verify_webhook(body, sign))
        self.assertEqual(self.fetch.call_count, 1)

    def test_refetch_throttled(self):
        other_priv, _pem = _keypair()
        body = self._body()
        self.assertTrue(self.journal._mono_verify_webhook(
            body, _sign(self.priv, body)))
        for _i in range(5):
            self.assertFalse(self.journal._mono_verify_webhook(
                body, _sign(other_priv, body)))
        # Перший запит ключа — і все: підробки не смикають API.
        self.assertEqual(self.fetch.call_count, 1)
