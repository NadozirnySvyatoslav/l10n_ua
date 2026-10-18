import base64
import json

from odoo.addons.payment.tests.common import PaymentCommon


class LiqPayCommon(PaymentCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.liqpay = cls._prepare_provider('liqpay', update_values={
            'liqpay_public_key': 'sandbox_i00000000',
            'liqpay_private_key': 'sandbox_a4825234f4bae72a0be04eafe9e8e2bada209255',
        })
        cls.provider = cls.liqpay
        cls.currency = cls.currency_euro

    def _payment_data(self, **values):
        """Callback `data` of a successful payment of the test transaction."""
        return {
            'action': 'pay',
            'amount': self.amount,
            'currency': self.currency.name,
            'order_id': self.reference,
            'payment_id': 1234567,
            'paytype': 'card',
            'public_key': self.liqpay.liqpay_public_key,
            'status': 'success',
            'version': 7,
            **values,
        }

    def _encode(self, payment_data, provider=None):
        """`data` and `signature` as LiqPay posts them to server_url."""
        provider = provider or self.liqpay
        data = base64.b64encode(json.dumps(payment_data).encode()).decode()
        return {'data': data, 'signature': provider._liqpay_sign(data)}

    @staticmethod
    def _decode(data):
        return json.loads(base64.b64decode(data))
