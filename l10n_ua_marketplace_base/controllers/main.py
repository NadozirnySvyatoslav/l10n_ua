import base64
import hashlib
import hmac
import json
import logging

import werkzeug.exceptions

from odoo import http, _
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class MarketplaceFeedController(http.Controller):
    """Controller for marketplace product feeds."""

    @http.route('/marketplace/feed/<int:backend_id>', type='http', auth='public', methods=['GET'])
    def get_feed(self, backend_id, **kwargs):
        """Return product feed for marketplace."""
        backend = request.env['marketplace.backend'].sudo().browse(backend_id)

        if not backend.exists():
            return Response('Backend not found', status=404)

        if not backend.feed_enabled:
            return Response('Feed disabled', status=403)

        # Check authentication if enabled
        if backend.feed_auth_enabled:
            auth = request.httprequest.authorization
            if not auth or not self._check_feed_auth(backend, auth):
                return Response(
                    'Unauthorized',
                    status=401,
                    headers={'WWW-Authenticate': 'Basic realm="Marketplace Feed"'}
                )

        try:
            feed_content = backend._generate_feed()
            content_type = 'application/xml; charset=utf-8'

            return Response(
                feed_content,
                content_type=content_type,
                headers={
                    'Content-Disposition': f'inline; filename="{backend.code}_feed.xml"',
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                }
            )
        except Exception as e:
            _logger.exception(f"Error generating feed for backend {backend_id}: {e}")
            return Response(f'Error generating feed: {e}', status=500)

    @http.route('/marketplace/feed/<int:backend_id>/yml', type='http', auth='public', methods=['GET'])
    def get_feed_yml(self, backend_id, **kwargs):
        """Return YML feed explicitly."""
        kwargs['format'] = 'yml'
        return self.get_feed(backend_id, **kwargs)

    @http.route('/marketplace/feed/<int:backend_id>/xml', type='http', auth='public', methods=['GET'])
    def get_feed_xml(self, backend_id, **kwargs):
        """Return XML feed explicitly."""
        kwargs['format'] = 'xml'
        return self.get_feed(backend_id, **kwargs)

    def _check_feed_auth(self, backend, auth):
        """Check Basic Auth credentials for feed access."""
        if auth.type != 'basic':
            return False
        return (
            auth.username == backend.feed_auth_login and
            auth.password == backend.feed_auth_password
        )


class MarketplaceWebhookController(http.Controller):
    """Controller for marketplace webhooks."""

    @http.route('/marketplace/webhook/<int:backend_id>', type='jsonrpc', auth='public',
                methods=['POST'], csrf=False)
    def webhook(self, backend_id, **kwargs):
        """Handle webhook from marketplace."""
        # Публічний webhook: бекенд потрібен для перевірки підпису, назовні не віддається.
        # sudo-ok: читаємо бекенд лише для перевірки підпису
        backend = request.env['marketplace.backend'].sudo().browse(backend_id)

        if not backend.exists():
            return {'error': 'Backend not found'}

        if not backend.webhook_enabled:
            return {'error': 'Webhook disabled'}

        # Підпис обов'язковий: без секрету або з хибним підписом — 403.
        # abort(Response) оминає handle_error jsonrpc і дає справжній HTTP 403.
        if not self._verify_signature(backend, request):
            _logger.warning("Webhook rejected for backend %s: signature check failed", backend_id)
            werkzeug.exceptions.abort(Response('Forbidden', status=403))

        # Get request data (request.jsonrequest прибрали ще в Odoo 17)
        try:
            data = request.get_json_data()
        except Exception:
            data = kwargs or {}

        # Log webhook data
        _logger.info(f"Webhook received for backend {backend.name}: {json.dumps(data)[:500]}")

        try:
            # Спершу — обробник конкретного майданчика, далі типовий шлях
            result = backend._process_webhook(data, request.httprequest.headers)
            if not result:
                result = self._process_webhook(backend, data)
            return {'success': True, 'result': result}
        except Exception as e:
            _logger.exception(f"Error processing webhook for backend {backend_id}: {e}")
            return {'error': str(e)}

    def _verify_signature(self, backend, req):
        """Verify webhook signature using HMAC.

        Fail-closed: якщо секрет не задано (або порожній), запит відхиляється.
        """
        secret = backend.webhook_secret or ''
        if not secret.strip():
            return False

        signature_header = req.httprequest.headers.get('X-Webhook-Signature')
        if not signature_header:
            signature_header = req.httprequest.headers.get('X-Signature')

        if not signature_header:
            return False

        # Get raw body
        body = req.httprequest.data

        # Calculate expected signature
        expected = hmac.new(
            secret.encode('utf-8'),
            body or b'',
            hashlib.sha256
        ).hexdigest()

        # Compare signatures (bytes: compare_digest не приймає не-ASCII str)
        return hmac.compare_digest(signature_header.encode('utf-8'), expected.encode('ascii'))

    def _process_webhook(self, backend, data):
        """Process webhook data. Override in specific marketplace modules."""
        event_type = data.get('event') or data.get('type') or data.get('action')

        if event_type in ('order.created', 'order.new', 'new_order'):
            return self._process_new_order(backend, data)
        elif event_type in ('order.updated', 'order.status_changed', 'status_change'):
            return self._process_order_update(backend, data)
        else:
            _logger.info(f"Unknown webhook event type: {event_type}")
            return {'event': event_type, 'processed': False}

    def _process_new_order(self, backend, data):
        """Process new order webhook."""
        # Trigger immediate order import
        try:
            count = backend._import_orders()
            return {'orders_imported': count}
        except Exception as e:
            _logger.exception(f"Error importing orders from webhook: {e}")
            raise

    def _process_order_update(self, backend, data):
        """Process order status update webhook."""
        order_id = data.get('order_id') or data.get('external_id')
        new_status = data.get('status') or data.get('new_status')

        if not order_id:
            return {'error': 'No order_id in webhook data'}

        order = request.env['marketplace.order'].sudo().search([
            ('backend_id', '=', backend.id),
            ('external_id', '=', str(order_id)),
        ], limit=1)

        if order:
            order.write({
                'marketplace_state': new_status,
            })
            return {'order_id': order_id, 'status_updated': True}
        else:
            return {'order_id': order_id, 'error': 'Order not found'}


class MarketplacePublicController(http.Controller):
    """Public pages for marketplace integration."""

    @http.route('/marketplace/status', type='http', auth='public', methods=['GET'])
    def status(self, **kwargs):
        """Health check endpoint."""
        return Response(
            json.dumps({'status': 'ok', 'service': 'marketplace'}),
            content_type='application/json'
        )
