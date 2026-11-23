import json
import logging
import traceback

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MonobankAcquiringWebhook(http.Controller):

    @http.route(
        '/l10n_ua_mono_acquiring/webhook',
        methods=['POST'],
        type='http',
        csrf=False,
        auth='public',
    )
    def mono_webhook(self):
        """Webhook Monobank Acquiring.

        Дані використовуються лише тоді, коли заголовок X-Sign — дійсний
        ECDSA-підпис тіла запиту ключем мерчанта журналу компанії, якій
        належить документ. Без підпису або з хибним підписом — 403.
        """
        ok = request.make_response('ok', [('Content-Type', 'text/plain')])
        body = request.httprequest.get_data()
        try:
            data = json.loads(body or b'{}')
        except ValueError:
            _logger.warning("Monobank webhook: malformed JSON")
            return request.make_response('bad request', status=400)
        if not isinstance(data, dict):
            return request.make_response('bad request', status=400)

        invoice_id = data.get('invoiceId')
        status = data.get('status')
        _logger.info("Monobank webhook: invoiceId=%s status=%s",
                     invoice_id, status)
        if not invoice_id or not isinstance(invoice_id, str):
            return ok

        # sudo-ok: публічний webhook; запис знаходимо лише для вибору ключа
        # перевірки підпису, змін до перевірки немає.
        record = request.env['sale.order'].sudo().search(
            [('mono_invoice_id', '=', invoice_id)], limit=1)
        if not record:
            # sudo-ok: те саме для рахунку.
            record = request.env['account.move'].sudo().search(
                [('mono_invoice_id', '=', invoice_id)], limit=1)
        if not record:
            _logger.warning("Monobank webhook: no order/invoice for "
                            "invoiceId=%s", invoice_id)
            return ok  # Не наш документ: Monobank нема чого повторювати.

        # sudo-ok: токени журналів читає лише сервер, назовні не віддаються.
        journals = request.env['account.journal'].sudo().search([
            ('type', '=', 'bank'),
            ('mono_acquiring_token', '!=', False),
            ('company_id', '=', record.company_id.id),
        ])
        x_sign = request.httprequest.headers.get('X-Sign')
        if not journals._mono_verify_webhook(body, x_sign):
            _logger.warning("Monobank webhook: invalid X-Sign for "
                            "invoiceId=%s", invoice_id)
            return request.make_response('forbidden', status=403)

        if status != 'success':
            return ok

        try:
            if record._name == 'sale.order':
                self._process_sale_order(record, data)
            else:
                self._process_invoice(record, data)
        except Exception:
            _logger.error("Monobank webhook error:\n%s", traceback.format_exc())
        return ok

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _process_sale_order(self, order, data):
        """Confirm order, create invoice, register payment."""
        _logger.info("Monobank webhook: processing sale.order %s", order.name)

        if order.state != 'sale':
            order.action_confirm()

        if order.invoice_status == 'to invoice':
            invoices = order._create_invoices()
            invoices.action_post()
        else:
            invoices = order.invoice_ids.filtered(
                lambda m: m.state == 'posted' and m.payment_state != 'paid')

        if invoices:
            request.env['account.payment.register'].sudo().with_context(
                active_ids=invoices.ids,
                active_model='account.move',
            ).create({})._create_payments()
        else:
            _logger.warning(
                "Monobank webhook: no invoices to pay for %s", order.name)

    def _process_invoice(self, move, data):
        """Register payment for existing posted invoice."""
        _logger.info("Monobank webhook: processing account.move %s", move.name)

        if move.state != 'posted':
            _logger.warning("Monobank webhook: invoice %s not posted", move.name)
            return

        if move.payment_state == 'paid':
            _logger.info(
                "Monobank webhook: invoice %s already paid", move.name)
            return

        request.env['account.payment.register'].sudo().with_context(
            active_ids=[move.id],
            active_model='account.move',
        ).create({})._create_payments()
