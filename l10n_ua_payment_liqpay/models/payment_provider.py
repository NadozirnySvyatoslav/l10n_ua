import base64
import hashlib
import hmac
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.l10n_ua_payment_liqpay import const


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('liqpay', "LiqPay")], ondelete={'liqpay': 'set default'})
    liqpay_public_key = fields.Char(
        string="LiqPay Public Key",
        help="public_key of the LiqPay shop: the sandbox_ key in test mode, the live one "
             "otherwise.",
        required_if_provider='liqpay', copy=False)
    liqpay_private_key = fields.Char(
        string="LiqPay Private Key",
        help="private_key of the LiqPay shop. It signs the requests and verifies the callbacks.",
        required_if_provider='liqpay', copy=False, groups='base.group_system')

    @api.constrains('state', 'liqpay_public_key', 'liqpay_private_key')
    def _check_liqpay_keys_match_state(self):
        """Sandbox keys never charge money: they belong to test mode and only there."""
        liqpay_providers = self.sudo().filtered(
            lambda p: p.code == 'liqpay' and p.state != 'disabled')
        for provider in liqpay_providers:
            keys = [k for k in (provider.liqpay_public_key, provider.liqpay_private_key) if k]
            sandbox = [k.startswith(const.SANDBOX_KEY_PREFIX) for k in keys]
            if provider.state == 'enabled' and any(sandbox):
                raise ValidationError(_(
                    "LiqPay sandbox keys (starting with \"sandbox_\") can only be used in test "
                    "mode. Enter the live keys or switch the provider to Test Mode."))
            if provider.state == 'test' and not all(sandbox):
                raise ValidationError(_(
                    "In test mode LiqPay needs the sandbox keys (starting with \"sandbox_\"); "
                    "live keys would charge real cards."))

    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'liqpay').update({
            'support_refund': 'partial',
        })

    def _get_supported_currencies(self):
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'liqpay':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES)
        return supported_currencies

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != 'liqpay':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === LiqPay data and signature === #

    @staticmethod
    def _liqpay_sign_with(private_key, data, digestmod):
        """base64_encode( hash( private_key + data + private_key ) )"""
        sign_string = f'{private_key}{data}{private_key}'.encode()
        return base64.b64encode(hashlib.new(digestmod, sign_string).digest()).decode()

    def _liqpay_sign(self, data):
        """Signature of a request: `base64_encode( sha3-256( private_key + data + private_key ) )`.

        https://www.liqpay.ua/doc/api/internet_acquiring/checkout
        """
        self.ensure_one()
        return self._liqpay_sign_with(self.sudo().liqpay_private_key, data, 'sha3_256')

    def _liqpay_encode(self, params):
        """Return the `data` and `signature` parameters of a LiqPay request."""
        self.ensure_one()
        data = base64.b64encode(json.dumps(params).encode()).decode()
        return data, self._liqpay_sign(data)

    def _liqpay_verify_signature(self, data, signature):
        """Whether `signature` was produced from `data` with the private key of the provider.

        The docs state SHA3-256 (https://www.liqpay.ua/doc/api/callback); their SDK snippets on the
        same page still compute SHA-1. Both are keyed with the private key, so both are accepted.
        """
        self.ensure_one()
        private_key = self.sudo().liqpay_private_key
        if not private_key or not data or not signature or not isinstance(signature, str):
            return False
        return any(
            hmac.compare_digest(self._liqpay_sign_with(private_key, data, digestmod), signature)
            for digestmod in ('sha3_256', 'sha1')
        )

    @staticmethod
    def _liqpay_decode(data):
        """Decode the `data` parameter. Raise ValueError if it is not base64-encoded JSON object."""
        try:
            payment_data = json.loads(base64.b64decode(data, validate=True))
        except (TypeError, ValueError) as error:
            raise ValueError("invalid LiqPay data") from error
        if not isinstance(payment_data, dict):
            raise ValueError("invalid LiqPay data")
        return payment_data

    # === Server-Server requests === #

    def _build_request_url(self, endpoint, **kwargs):
        if self.code != 'liqpay':
            return super()._build_request_url(endpoint, **kwargs)
        return const.API_URL

    def _liqpay_api_request(self, params, reference=None):
        """POST `data` and `signature` to https://www.liqpay.ua/api/request."""
        self.ensure_one()
        data, signature = self._liqpay_encode({
            'version': const.API_VERSION,
            'public_key': self.liqpay_public_key,
            **params,
        })
        return self._send_api_request(
            'POST', 'request', data={'data': data, 'signature': signature}, reference=reference)
