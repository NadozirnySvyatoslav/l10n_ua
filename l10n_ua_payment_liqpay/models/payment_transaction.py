from werkzeug.urls import url_encode

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round, urls

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.l10n_ua_payment_liqpay import const
from odoo.addons.l10n_ua_payment_liqpay.controllers.main import LiqPayController

_logger = get_payment_logger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _get_specific_rendering_values(self, processing_values):
        if self.provider_code != 'liqpay':
            return super()._get_specific_rendering_values(processing_values)

        data, signature = self.provider_id._liqpay_encode(self._liqpay_prepare_checkout_params())
        return {'api_url': const.CHECKOUT_URL, 'data': data, 'signature': signature}

    def _liqpay_amount(self, amount=None):
        """Amount as a JSON number with the decimals of the currency."""
        return float_round(
            self.amount if amount is None else amount,
            precision_digits=self.currency_id.decimal_places)

    def _liqpay_description(self):
        """Purpose of the payment, in the language of the customer."""
        return _("Payment for order %s", self.reference)

    def _liqpay_prepare_checkout_params(self):
        """Parameters of `data` for the Checkout (action `pay`)."""
        base_url = self.provider_id.get_base_url()
        query = url_encode({'ref': self.reference})
        customer_tx = self.with_context(lang=self.partner_lang) if self.partner_lang else self
        return {
            'version': const.API_VERSION,
            'public_key': self.provider_id.liqpay_public_key,
            'action': 'pay',
            'amount': self._liqpay_amount(),
            'currency': self.currency_id.name,
            'description': customer_tx._liqpay_description(),
            'order_id': self.reference,
            'language': 'uk' if (self.partner_lang or '').startswith('uk') else 'en',
            'result_url': f"{urls.urljoin(base_url, LiqPayController._return_url)}?{query}",
            'server_url': urls.urljoin(base_url, LiqPayController._webhook_url),
        }

    # === Refunds === #

    def _send_refund_request(self):
        if self.provider_code != 'liqpay':
            return super()._send_refund_request()

        # https://www.liqpay.ua/doc/api/internet_acquiring/refund
        response = self.provider_id._liqpay_api_request({
            'action': 'refund',
            'amount': self._liqpay_amount(-self.amount),
            'order_id': self.source_transaction_id.reference,
        }, reference=self.reference)
        if response.get('payment_id'):
            self.provider_reference = str(response['payment_id'])
        status = response.get('status')
        if response.get('result') == 'error' or status in const.STATUS_MAPPING['error']:
            raise ValidationError(_(
                "LiqPay refused the refund: %s",
                response.get('err_description') or response.get('err_code') or status))
        if response.get('result') == 'ok' and status in const.STATUS_MAPPING['reversed']:
            self._set_done()
        else:
            # Confirmed later by the `reversed` callback of the payment.
            self._set_pending()

    # === Processing === #

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        if provider_code != 'liqpay':
            return super()._extract_reference(provider_code, payment_data)
        return payment_data.get('order_id')

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'liqpay':
            return super()._extract_amount_data(payment_data)

        if (payment_data.get('status') in const.STATUS_MAPPING['reversed']
                and self.state == 'done'):
            # A refund of a paid order: the refunded amount is bounded by the payment in
            # `_liqpay_process_reversal` instead.
            return None
        try:
            amount = float(payment_data.get('amount') or 0)
        except (TypeError, ValueError):
            amount = 0
        return {'amount': amount, 'currency_code': payment_data.get('currency')}

    def _apply_updates(self, payment_data):
        if self.provider_code != 'liqpay':
            return super()._apply_updates(payment_data)

        if payment_data.get('payment_id'):
            self.provider_reference = str(payment_data['payment_id'])
        payment_method = self.env['payment.method']._get_from_code(
            payment_data.get('paytype'), mapping=const.PAYMENT_METHODS_MAPPING)
        self.payment_method_id = payment_method or self.payment_method_id

        status = payment_data.get('status')
        if status in const.STATUS_MAPPING['done']:
            self._set_done()
        elif status == const.SANDBOX_STATUS:
            if self.provider_id.state == 'test':
                self._set_done()
            else:
                _logger.warning("sandbox payment received for live transaction %s", self.reference)
                self._set_error(
                    _("LiqPay reported a sandbox (test) payment for a live transaction."))
        elif status in const.STATUS_MAPPING['pending']:
            self._set_pending()
        elif status in const.STATUS_MAPPING['reversed']:
            if self.state == 'done':
                self._liqpay_process_reversal(payment_data)
            else:
                self._set_canceled(_("LiqPay payment status: %s", status))
        elif status in const.STATUS_MAPPING['error']:
            self._set_error(_(
                "The payment was declined: %s",
                payment_data.get('err_description') or payment_data.get('err_code') or status))
        else:
            _logger.warning("unknown LiqPay status %s for %s", status, self.reference)
            self._set_error(_("Received data with invalid payment status: %s.", status))

    def _liqpay_process_reversal(self, payment_data):
        """Record the refunds of a paid transaction reported by a `reversed` callback.

        The callback carries the order_id of the payment, not of the refund. Refunds requested from
        Odoo and still pending are confirmed first; whatever LiqPay reports beyond that (a refund
        made in the LiqPay cabinet) becomes a new refund transaction.
        """
        self.ensure_one()
        try:
            refunded = float(payment_data.get('refund_amount') or payment_data.get('amount') or 0)
        except (TypeError, ValueError):
            refunded = 0
        currency = self.currency_id
        refunded = min(refunded, self.amount)
        if currency.is_zero(refunded) or payment_data.get('currency') not in (None, currency.name):
            _logger.warning("ignoring LiqPay refund data for %s", self.reference)
            return

        refunds = self.child_transaction_ids.filtered(lambda tx: tx.operation == 'refund')
        done_amount = -sum(refunds.filtered(lambda tx: tx.state == 'done').mapped('amount'))
        for refund_tx in refunds.filtered(lambda tx: tx.state == 'pending').sorted('id'):
            if currency.compare_amounts(done_amount - refund_tx.amount, refunded) > 0:
                break
            refund_tx._set_done()
            done_amount -= refund_tx.amount
        missing = currency.round(refunded - done_amount)
        if currency.compare_amounts(missing, 0) > 0:
            refund_tx = self._create_child_transaction(missing, is_refund=True)
            refund_tx._set_done()
