import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged

SECRET = 'test-marketplace-secret'


@tagged('post_install', '-at_install')
class TestMarketplaceWebhookSecret(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env['marketplace.backend'].create({
            'name': 'Test webhook backend',
            'marketplace_type': 'prom',
            'webhook_enabled': True,
            'webhook_secret': SECRET,
        })
        cls.url = f'/marketplace/webhook/{cls.backend.id}'
        cls.body = json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 1,
            'params': {'event': 'ping'},
        }).encode()

    def _post(self, signature=None):
        headers = {'Content-Type': 'application/json'}
        if signature is not None:
            headers['X-Webhook-Signature'] = signature
        return self.url_open(self.url, data=self.body, headers=headers)

    def _sign(self, secret, body=None):
        return hmac.new(secret.encode(), body or self.body, hashlib.sha256).hexdigest()

    def test_no_secret_configured_rejected(self):
        self.backend.webhook_secret = False
        resp = self._post(self._sign(SECRET))
        self.assertEqual(resp.status_code, 403)

    def test_blank_secret_rejected(self):
        """Порожній секрет — це не «перевірку вимкнено»."""
        for blank in ('', '   '):
            self.backend.webhook_secret = blank
            # підпис, обчислений з тим самим порожнім ключем, теж не пройде
            resp = self._post(self._sign(blank))
            self.assertEqual(resp.status_code, 403, repr(blank))

    def test_missing_signature_rejected(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 403)

    def test_wrong_secret_rejected(self):
        resp = self._post(self._sign('other-secret'))
        self.assertEqual(resp.status_code, 403)

    def test_non_ascii_signature_rejected(self):
        resp = self._post('підпис'.encode('utf-8'))
        self.assertEqual(resp.status_code, 403)

    def test_tampered_body_rejected(self):
        tampered = self.body.replace(b'ping', b'pong')
        resp = self.url_open(self.url, data=tampered, headers={
            'Content-Type': 'application/json',
            'X-Webhook-Signature': self._sign(SECRET),
        })
        self.assertEqual(resp.status_code, 403)

    def test_valid_secret_accepted(self):
        resp = self._post(self._sign(SECRET))
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertNotIn('error', payload)
        self.assertTrue(payload['result'].get('success'), payload)
