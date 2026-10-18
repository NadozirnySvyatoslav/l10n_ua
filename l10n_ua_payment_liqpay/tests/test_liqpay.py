from unittest.mock import Mock, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.payment.tests.http_common import PaymentHttpCommon
from odoo.addons.l10n_ua_payment_liqpay import const
from odoo.addons.l10n_ua_payment_liqpay.controllers.main import LiqPayController
from odoo.addons.l10n_ua_payment_liqpay.tests.common import LiqPayCommon

REQUESTS = 'odoo.addons.payment.models.payment_provider.requests.request'

# https://www.liqpay.ua/doc/api/internet_acquiring/checkout — "Формування data і signature"
DOC_PRIVATE_KEY = 'a4825234f4bae72a0be04eafe9e8e2bada209255'
DOC_DATA = (
    'eyJwdWJsaWNfa2V5IjoiaTAwMDAwMDAwIiwidmVyc2lvbiI6NywiYWN0aW9uIjoicGF5IiwiYW1vdW50IjoiMyIsImN1'
    'cnJlbmN5IjoiVUFIIiwiZGVzY3JpcHRpb24iOiJ0ZXN0Iiwib3JkZXJfaWQiOiIwMDAwMDEifQ=='
)
DOC_SIGNATURE = '0adgJ8F2Ds5HCVkcz4AlmdLMRoIJf7IxsL3QmeFRz/s='
# Same page, the SDK (bash) example, still SHA-1: base64 output wrapped at 76 characters.
DOC_SHA1_PRIVATE_KEY = 'your_private_key'
DOC_SHA1_DATA = (
    'eyAidmVyc2lvbiIgOiAzLCAicHVibGljX2tleSIgOiAieW91cl9wdWJsaWNfa2V5IiwgImFjdGlv\n'
    'biIgOiAicGF5IiwgImFtb3VudCIgOiAxLCAiY3VycmVuY3kiIDogIlVTRCIsICJkZXNjcmlwdGlv\n'
    'biIgOiAiZGVzY3JpcHRpb24gdGV4dCIsICJvcmRlcl9pZCIgOiAib3JkZXJfaWRfMSIgfQ=='
)
DOC_SHA1_SIGNATURE = 'QvJD5u9Fg55PCx/Hdz6lzWtYwcI='


def _api_response(content):
    response = Mock(status_code=200, reason='OK', url=const.API_URL, text=str(content))
    response.json.return_value = content
    response.raise_for_status.return_value = None
    return response


@tagged('post_install', '-at_install')
class TestLiqPay(LiqPayCommon, PaymentHttpCommon):

    # --- signature --- #

    def test_signature_matches_documented_example(self):
        provider = self.liqpay
        self.assertEqual(
            provider._liqpay_sign_with(DOC_PRIVATE_KEY, DOC_DATA, 'sha3_256'), DOC_SIGNATURE)
        self.assertEqual(self._decode(DOC_DATA), {
            'public_key': 'i00000000', 'version': 7, 'action': 'pay', 'amount': '3',
            'currency': 'UAH', 'description': 'test', 'order_id': '000001'})

    def test_verify_signature_sha3_and_sha1(self):
        provider = self.liqpay
        provider.liqpay_private_key = 'sandbox_' + DOC_PRIVATE_KEY
        data = self._encode({'order_id': 'x'})['data']
        self.assertTrue(provider._liqpay_verify_signature(data, provider._liqpay_sign(data)))
        sha1 = provider._liqpay_sign_with(provider.liqpay_private_key, data, 'sha1')
        self.assertTrue(provider._liqpay_verify_signature(data, sha1))
        self.assertFalse(provider._liqpay_verify_signature(data, DOC_SIGNATURE))
        self.assertFalse(provider._liqpay_verify_signature(data, ''))
        self.assertFalse(provider._liqpay_verify_signature(data + 'x', sha1))
        self.assertEqual(
            provider._liqpay_sign_with(DOC_SHA1_PRIVATE_KEY, DOC_SHA1_DATA, 'sha1'),
            DOC_SHA1_SIGNATURE)

    # --- checkout form --- #

    def test_redirect_form_values(self):
        self.patch(type(self.env['base']), 'get_base_url', lambda _: 'https://shop.example.com')
        self.partner.lang = 'en_US'
        tx = self._create_transaction(flow='redirect')
        with mute_logger('odoo.addons.payment.models.payment_transaction'):
            processing_values = tx._get_processing_values()
        form = self._extract_values_from_html_form(processing_values['redirect_form_html'])

        self.assertEqual(form['action'], 'https://www.liqpay.ua/api/3/checkout')
        self.assertEqual(form['method'], 'post')
        self.assertEqual(set(form['inputs']), {'data', 'signature'})
        data = form['inputs']['data']
        self.assertEqual(form['inputs']['signature'], self.liqpay._liqpay_sign(data))
        self.assertDictEqual(self._decode(data), {
            'version': 7,
            'public_key': 'sandbox_i00000000',
            'action': 'pay',
            'amount': 1111.11,
            'currency': 'EUR',
            'description': 'Payment for order Test Transaction',
            'order_id': 'Test Transaction',
            'language': 'en',
            'result_url': 'https://shop.example.com/payment/liqpay/return?ref=Test+Transaction',
            'server_url': 'https://shop.example.com/payment/liqpay/webhook',
        })
        self.assertNotIn(self.liqpay.liqpay_private_key, data)

    def test_checkout_language(self):
        self.env['res.lang']._activate_lang('uk_UA')
        self.partner.lang = 'uk_UA'
        tx = self._create_transaction(flow='redirect')
        self.assertEqual(tx._liqpay_prepare_checkout_params()['language'], 'uk')

    def test_supported_currencies(self):
        currencies = self.env['res.currency'].with_context(active_test=False).search(
            [('name', 'in', ['UAH', 'USD', 'EUR', 'PLN', 'GBP'])])
        currencies.active = True
        self.assertEqual(
            sorted(self.liqpay._get_supported_currencies().mapped('name')),
            ['EUR', 'UAH', 'USD'])
        self.assertEqual(self.liqpay.support_refund, 'partial')

    # --- callback --- #

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.controllers.main')
    def test_webhook_valid_signature_confirms(self):
        tx = self._create_transaction('redirect')
        url = self._build_url(LiqPayController._webhook_url)
        response = self._make_http_post_request(url, data=self._encode(self._payment_data()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.provider_reference, '1234567')
        self.assertEqual(tx.payment_method_id, self.env.ref('payment.payment_method_card'))

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.controllers.main')
    def test_webhook_invalid_signature_rejected(self):
        tx = self._create_transaction('redirect')
        url = self._build_url(LiqPayController._webhook_url)
        payload = self._encode(self._payment_data())
        payload['signature'] = DOC_SIGNATURE
        response = self._make_http_post_request(url, data=payload)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(tx.state, 'draft')

        # Signed with another shop's key.
        other = self.liqpay.copy({'liqpay_public_key': 'sandbox_other'})
        other.liqpay_private_key = 'sandbox_other_private'
        response = self._make_http_post_request(
            url, data=self._encode(self._payment_data(), provider=other))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(tx.state, 'draft')

        # Missing signature, malformed data.
        payload.pop('signature')
        self.assertEqual(self._make_http_post_request(url, data=payload).status_code, 403)
        response = self._make_http_post_request(url, data={'data': '%%%', 'signature': 'x'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(tx.state, 'draft')

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.controllers.main')
    def test_webhook_other_public_key_rejected(self):
        tx = self._create_transaction('redirect')
        url = self._build_url(LiqPayController._webhook_url)
        payload = self._encode(self._payment_data(public_key='sandbox_i99999999'))
        self.assertEqual(self._make_http_post_request(url, data=payload).status_code, 403)
        self.assertEqual(tx.state, 'draft')

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.models.payment_transaction')
    def test_status_mapping(self):
        expected = {status: state for state, statuses in [
            ('done', const.STATUS_MAPPING['done']),
            ('pending', const.STATUS_MAPPING['pending']),
            ('error', const.STATUS_MAPPING['error']),
            ('cancel', const.STATUS_MAPPING['reversed']),
        ] for status in statuses}
        expected.update({'subscribed': 'error', 'whatever': 'error'})
        for i, (status, state) in enumerate(expected.items()):
            with self.subTest(status=status):
                reference = f'Test Transaction {i}'
                tx = self._create_transaction('redirect', reference=reference)
                tx._process('liqpay', self._payment_data(order_id=reference, status=status))
                self.assertEqual(tx.state, state)

    def test_failure_keeps_message(self):
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(
            status='failure', err_code='limit', err_description='Exceeded the limit'))
        self.assertEqual(tx.state, 'error')
        self.assertIn('Exceeded the limit', tx.state_message)

    @mute_logger('odoo.addons.payment.models.payment_transaction')
    def test_amount_or_currency_mismatch_rejected(self):
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(amount=1.0))
        self.assertEqual(tx.state, 'error')

        self.reference = 'Test Transaction 2'
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(currency='UAH'))
        self.assertEqual(tx.state, 'error')

        self.reference = 'Test Transaction 3'
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(amount=None))
        self.assertEqual(tx.state, 'error')

    def test_amount_as_string_accepted(self):
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(amount='1111.11'))
        self.assertEqual(tx.state, 'done')

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.models.payment_transaction')
    def test_sandbox_status_only_in_test_mode(self):
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(status='sandbox'))
        self.assertEqual(tx.state, 'done')

        self.liqpay.write({
            'state': 'enabled',
            'liqpay_public_key': 'i00000000',
            'liqpay_private_key': DOC_PRIVATE_KEY,
        })
        self.reference = 'Test Transaction 2'
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data(status='sandbox'))
        self.assertEqual(tx.state, 'error')

    def test_sandbox_keys_only_in_test_mode(self):
        with self.assertRaises(ValidationError):
            self.liqpay.state = 'enabled'
        with self.assertRaises(ValidationError):
            self.liqpay.write({'liqpay_public_key': 'i00000000', 'liqpay_private_key': 'live'})
        self.liqpay.write({
            'state': 'enabled', 'liqpay_public_key': 'i00000000', 'liqpay_private_key': 'live'})

    # --- return from checkout --- #

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.controllers.main')
    def test_return_queries_status_api(self):
        tx = self._create_transaction('redirect')
        status = dict(self._payment_data(), result='ok')
        with patch(REQUESTS, return_value=_api_response(status)) as request_mock:
            self._make_http_get_request(
                self._build_url(LiqPayController._return_url), params={'ref': self.reference})
        self.assertEqual(tx.state, 'done')
        sent = request_mock.call_args.kwargs['data']
        self.assertEqual(request_mock.call_args.args, ('POST', const.API_URL))
        self.assertEqual(sent['signature'], self.liqpay._liqpay_sign(sent['data']))
        self.assertEqual(self._decode(sent['data']), {
            'version': 7, 'public_key': 'sandbox_i00000000',
            'action': 'status', 'order_id': self.reference})

    @mute_logger('odoo.addons.l10n_ua_payment_liqpay.controllers.main')
    def test_return_ignores_unknown_payment(self):
        tx = self._create_transaction('redirect')
        not_found = {'result': 'error', 'status': 'error', 'err_code': 'payment_not_found'}
        with patch(REQUESTS, return_value=_api_response(not_found)):
            self._make_http_get_request(
                self._build_url(LiqPayController._return_url), params={'ref': self.reference})
        self.assertEqual(tx.state, 'draft')

    # --- refunds --- #

    def _paid_tx(self):
        tx = self._create_transaction('redirect')
        tx._process('liqpay', self._payment_data())
        self.assertEqual(tx.state, 'done')
        return tx

    def test_refund_request_payload(self):
        tx = self._paid_tx()
        response = {'result': 'ok', 'wait_amount': 'true', 'payment_id': '2417662437',
                    'status': 'reversed'}
        with patch(REQUESTS, return_value=_api_response(response)) as request_mock:
            refund_tx = tx._refund(amount_to_refund=100.5)
        sent = request_mock.call_args.kwargs['data']
        self.assertEqual(sent['signature'], self.liqpay._liqpay_sign(sent['data']))
        self.assertEqual(self._decode(sent['data']), {
            'version': 7, 'public_key': 'sandbox_i00000000', 'action': 'refund',
            'amount': 100.5, 'order_id': self.reference})
        self.assertEqual(refund_tx.state, 'done')
        self.assertEqual(refund_tx.amount, -100.5)
        self.assertEqual(refund_tx.provider_reference, '2417662437')

        # The reversed callback that follows does not refund twice.
        tx._process('liqpay', self._payment_data(status='reversed', refund_amount=100.5))
        self.assertEqual(tx.state, 'done')
        self.assertEqual(len(tx.child_transaction_ids), 1)

    def test_refund_refused(self):
        tx = self._paid_tx()
        response = {'result': 'error', 'status': 'error', 'err_description': 'not enough funds'}
        with patch(REQUESTS, return_value=_api_response(response)):
            refund_tx = tx._refund()
        self.assertEqual(refund_tx.state, 'error')
        self.assertIn('not enough funds', refund_tx.state_message)

    def test_pending_refund_confirmed_by_callback(self):
        tx = self._paid_tx()
        response = {'result': 'ok', 'status': 'processing'}
        with patch(REQUESTS, return_value=_api_response(response)):
            refund_tx = tx._refund(amount_to_refund=200)
        self.assertEqual(refund_tx.state, 'pending')
        tx._process('liqpay', self._payment_data(status='reversed', refund_amount=200))
        self.assertEqual(refund_tx.state, 'done')
        self.assertEqual(len(tx.child_transaction_ids), 1)

    def test_cabinet_refund_creates_refund_tx(self):
        tx = self._paid_tx()
        tx._process('liqpay', self._payment_data(status='reversed'))
        self.assertEqual(tx.state, 'done')
        refund_tx = tx.child_transaction_ids
        self.assertEqual(refund_tx.operation, 'refund')
        self.assertEqual(refund_tx.state, 'done')
        self.assertEqual(refund_tx.amount, -self.amount)
