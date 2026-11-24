import json

from odoo.tests import HttpCase, tagged

SECRET = 'a' * 64
TOKEN = '123456789:AAtestTOKENabcdefghij'
HEADER = 'X-Telegram-Bot-Api-Secret-Token'


@tagged('post_install', '-at_install')
class TestTelegramWebhookSecret(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bot = cls.env['telegram.bot'].create({
            'name': 'Test bot',
            'token': TOKEN,
        })
        cls.bot.write({'state': 'running', 'webhook_secret': SECRET})
        cls.url = f'/telegram/webhook/{TOKEN[-10:]}'
        cls.body = json.dumps({'update_id': 1}).encode()

    def _post(self, secret=None, url=None):
        headers = {'Content-Type': 'application/json'}
        if secret is not None:
            headers[HEADER] = secret
        return self.url_open(url or self.url, data=self.body, headers=headers)

    def test_no_secret_configured_rejected(self):
        self.bot.webhook_secret = False
        self.assertEqual(self._post().status_code, 403)
        self.assertEqual(self._post('anything').status_code, 403)

    def test_blank_secret_rejected(self):
        for blank in ('', '   '):
            self.bot.webhook_secret = blank
            # заголовок з тим самим «порожнім» значенням (requests не шле пробіли)
            self.assertEqual(self._post(blank.strip()).status_code, 403, repr(blank))
            self.assertEqual(self._post().status_code, 403, repr(blank))

    def test_missing_header_rejected(self):
        self.assertEqual(self._post().status_code, 403)

    def test_wrong_secret_rejected(self):
        self.assertEqual(self._post('b' * 64).status_code, 403)

    def test_non_ascii_secret_rejected(self):
        self.assertEqual(self._post('секрет'.encode('utf-8')).status_code, 403)

    def test_valid_secret_accepted(self):
        resp = self._post(SECRET)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get('ok'))

    def test_like_wildcard_in_url_not_matching(self):
        """% і _ у шляху не мають знаходити бота."""
        for path in ('/telegram/webhook/%25', '/telegram/webhook/' + '_' * 10):
            self.assertEqual(self._post(SECRET, url=path).status_code, 404, path)
