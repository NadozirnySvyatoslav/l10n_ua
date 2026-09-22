"""Тести Open Banking (PSD2 / Berlin Group) провайдера — #198 (мок API)."""

from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

MODULE = 'odoo.addons.l10n_ua_bank_openbanking.models.l10n_ua_bank_openbanking_config'

BOOKED = {
    'transactions': {
        'booked': [
            {'transactionId': 't1', 'bookingDate': '2018-06-01',
             'transactionAmount': {'amount': '-100.11', 'currency': 'UAH'},
             'creditorName': 'ТОВ Постачальник',
             'creditorAccount': {'iban': 'UA113052990000026007891234567'},
             'remittanceInformationUnstructured': 'оплата за товар'},
            {'transactionId': 't2', 'bookingDate': '2018-06-02',
             'transactionAmount': {'amount': '2500.50', 'currency': 'UAH'},
             'debtorName': 'ТОВ Клієнт',
             'debtorAccount': {'iban': 'UA223003350000026001112223334'},
             'remittanceInformationUnstructured': 'надходження'},
        ],
        'pending': [
            {'transactionId': 'p1',
             'transactionAmount': {'amount': '-9.99'}},
        ],
    }
}


def _fake_response(json_data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    return resp


@tagged('post_install', '-at_install')
class TestOpenBanking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        journal = cls.env['account.journal'].create({
            'name': 'OB', 'type': 'bank', 'code': 'OBNK'})
        partner = cls.env['res.partner'].create({'name': 'C'})
        acc = cls.env['res.partner.bank'].create({
            'account_number': '26001112223334', 'partner_id': partner.id})
        cls.config = cls.env['l10n_ua.bank.sync.config'].create({
            'name': 'OB', 'provider': 'openbanking',
            'journal_id': journal.id, 'bank_account_id': acc.id,
            'ob_base_url': 'https://api.bank.example',
            'ob_token_url': 'https://api.bank.example/token',
            'ob_client_id': 'cid', 'ob_client_secret': 'secret',
            'ob_account_resource_id': 'acc-123',
            'ob_consent_id': 'consent-1',
            'ob_consent_valid_until': date.today() + timedelta(days=30),
        })

    def test_parse_booked_debit_credit(self):
        txs = self.config._parse_transactions(BOOKED)
        # pending ігнорується → 2 транзакції.
        self.assertEqual(len(txs), 2)
        d, c = txs[0], txs[1]
        self.assertAlmostEqual(d['amount'], -100.11, places=2)
        self.assertEqual(d['date'], '2018-06-01')
        self.assertEqual(d['partner_name'], 'ТОВ Постачальник')
        self.assertEqual(d['partner_iban'], 'UA113052990000026007891234567')
        self.assertEqual(d['description'], 'оплата за товар')
        self.assertEqual(d['id'], 't1')
        self.assertAlmostEqual(c['amount'], 2500.50, places=2)
        self.assertEqual(c['partner_name'], 'ТОВ Клієнт')
        self.assertEqual(c['partner_iban'], 'UA223003350000026001112223334')

    def test_parse_empty(self):
        self.assertEqual(self.config._parse_transactions({}), [])
        self.assertEqual(
            self.config._parse_transactions(
                {'transactions': {'booked': []}}), [])

    def test_consent_valid(self):
        self.assertTrue(self.config.action_check_consent())

    def test_consent_expired_raises(self):
        self.config.ob_consent_valid_until = date.today() - timedelta(days=1)
        with self.assertRaises(UserError):
            self.config.action_check_consent()

    def test_consent_missing_raises(self):
        self.config.ob_consent_id = False
        with self.assertRaises(UserError):
            self.config.action_check_consent()

    def test_get_token(self):
        with patch('%s.requests.post' % MODULE,
                   return_value=_fake_response({'access_token': 'TOK'})) as m:
            token = self.config._ob_get_token()
        self.assertEqual(token, 'TOK')
        self.assertIn('grant_type', m.call_args.kwargs['data'])

    def test_fetch_full_flow(self):
        with patch('%s.requests.post' % MODULE,
                   return_value=_fake_response({'access_token': 'TOK'})), \
             patch('%s.requests.get' % MODULE,
                   return_value=_fake_response(BOOKED)) as mget:
            raw = self.config._fetch_from_bank(
                date(2018, 6, 1), date(2018, 6, 30))
        # Bearer + Consent-ID у заголовках, bookingStatus=booked.
        headers = mget.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer TOK')
        self.assertEqual(headers['Consent-ID'], 'consent-1')
        self.assertEqual(mget.call_args.kwargs['params']['bookingStatus'],
                         'booked')
        self.assertEqual(len(self.config._parse_transactions(raw)), 2)

    def test_pisp_payload(self):
        payload = self.config._ob_payment_payload(
            'UA11PAYER', 'ТОВ Отримувач', 'UA22RECIP', 1500.50,
            purpose='оплата')
        self.assertEqual(payload['debtorAccount']['iban'], 'UA11PAYER')
        self.assertEqual(payload['creditorAccount']['iban'], 'UA22RECIP')
        self.assertEqual(payload['instructedAmount']['amount'], '1500.50')

    def test_non_ob_delegates(self):
        other = self.env['l10n_ua.bank.sync.config'].create({
            'name': 'M', 'provider': 'manual',
            'journal_id': self.config.journal_id.id,
            'bank_account_id': self.config.bank_account_id.id})
        with self.assertRaises(NotImplementedError):
            other._parse_transactions(BOOKED)
