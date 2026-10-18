from werkzeug.exceptions import BadRequest, Forbidden

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

from odoo.addons.payment.logging import get_payment_logger

_logger = get_payment_logger(__name__)


class LiqPayController(http.Controller):
    _return_url = '/payment/liqpay/return'
    _webhook_url = '/payment/liqpay/webhook'

    @http.route(_return_url, type='http', auth='public', methods=['GET', 'POST'], csrf=False,
                save_session=False)
    def liqpay_return_from_checkout(self, **data):
        """Customer coming back from the LiqPay checkout (`result_url`).

        Nothing the browser sends is trusted: the payment status of the order named in the URL is
        asked from the LiqPay API with our own keys, so the status page is up to date even when the
        callback is late.
        """
        reference = data.get('ref')
        _logger.info("handling redirection from LiqPay for %s", reference)
        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference(
            'liqpay', {'order_id': reference})
        if tx_sudo and tx_sudo.state in ('draft', 'pending', 'error'):
            try:
                # https://www.liqpay.ua/doc/api/information/status_payment
                status_data = tx_sudo.provider_id._liqpay_api_request(
                    {'action': 'status', 'order_id': tx_sudo.reference},
                    reference=tx_sudo.reference)
            except ValidationError:
                _logger.error("unable to fetch the LiqPay status of %s", tx_sudo.reference)
            else:
                if (status_data.get('result') == 'ok'
                        and status_data.get('order_id') == tx_sudo.reference):
                    tx_sudo._process('liqpay', status_data)
        return request.redirect('/payment/status')

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def liqpay_webhook(self, **post):
        """Callback sent by LiqPay to `server_url`: POST `data` and `signature`.

        https://www.liqpay.ua/doc/api/callback — the payment data is used only once the signature,
        computed with the private key of the provider of the transaction, matches.
        """
        data, signature = post.get('data'), post.get('signature')
        try:
            payment_data = request.env['payment.provider']._liqpay_decode(data)
        except ValueError:
            _logger.warning("received a LiqPay callback with malformed data")
            raise BadRequest()
        reference = payment_data.get('order_id')
        _logger.info("notification received from LiqPay for %s: %s",
                     reference, payment_data.get('status'))

        tx_sudo = request.env['payment.transaction'].sudo()._search_by_reference(
            'liqpay', payment_data)
        if not tx_sudo:
            return ''  # Not ours: acknowledge, LiqPay has nothing to retry.
        provider_sudo = tx_sudo.provider_id
        if not provider_sudo._liqpay_verify_signature(data, signature):
            _logger.warning(
                "received a LiqPay callback with an invalid signature for %s", reference)
            raise Forbidden()
        if payment_data.get('public_key') not in (None, provider_sudo.liqpay_public_key):
            _logger.warning("received a LiqPay callback for another shop for %s", reference)
            raise Forbidden()
        try:
            tx_sudo._process('liqpay', payment_data)
        except ValidationError:
            _logger.exception("unable to process the LiqPay callback of %s", reference)
        return ''
