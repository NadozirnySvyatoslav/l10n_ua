import hmac
import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class TelegramWebhookController(http.Controller):

    @http.route(
        '/telegram/webhook/<string:token_hash>',
        type='http',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def telegram_webhook(self, token_hash, **kwargs):
        """Handle incoming Telegram webhook updates"""

        # Find bot by token hash: точний збіг хвоста токена, без LIKE-шаблонів
        # (% і _ з URL не мають підходити під довільного бота).
        # Публічний webhook: бот потрібен для перевірки секрету, токен назовні не віддається.
        # sudo-ok: шукаємо бота лише для перевірки секрету
        bots = request.env['telegram.bot'].sudo().search([
            ('state', '=', 'running'),
        ])
        bot = bots.filtered(lambda b: b.token and self._token_hash(b.token) == token_hash)[:1]

        if not bot:
            _logger.warning(f"No bot found for token hash: {token_hash}")
            return Response(
                json.dumps({'ok': False, 'error': 'Bot not found'}),
                content_type='application/json',
                status=404
            )

        # Секрет обов'язковий (fail-closed): без нього або з хибним — 403
        secret_token = request.httprequest.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if not self._check_secret(bot.webhook_secret, secret_token):
            _logger.warning("Webhook rejected for bot %s: secret check failed", bot.name)
            return Response(
                json.dumps({'ok': False, 'error': 'Invalid secret'}),
                content_type='application/json',
                status=403
            )

        # Get update data from raw request body
        try:
            update = json.loads(request.httprequest.data.decode('utf-8'))
        except Exception as e:
            _logger.error(f"Failed to parse webhook data: {e}")
            return Response(
                json.dumps({'ok': False, 'error': 'Invalid JSON'}),
                content_type='application/json',
                status=400
            )

        _logger.info(f"Received update for bot {bot.name}: {json.dumps(update)[:500]}")

        try:
            self._process_update(bot, update)
        except Exception as e:
            _logger.exception(f"Error processing update: {e}")
            # Don't return error to Telegram, or it will retry
            bot.last_error = str(e)

        return Response(
            json.dumps({'ok': True}),
            content_type='application/json',
            status=200
        )

    @staticmethod
    def _token_hash(token):
        """Те саме, що в telegram.bot._compute_webhook_url."""
        return token[-10:] if len(token) > 10 else token

    @staticmethod
    def _check_secret(expected, received):
        """Fail-closed: порожній/незаданий секрет — завжди відмова."""
        if not expected or not expected.strip() or not received:
            return False
        return hmac.compare_digest(expected.encode('utf-8'), received.encode('utf-8'))

    def _process_update(self, bot, update):
        """Process a Telegram update"""

        if 'message' in update:
            self._handle_message(bot, update['message'])

        elif 'callback_query' in update:
            self._handle_callback(bot, update['callback_query'])

        elif 'my_chat_member' in update:
            self._handle_chat_member(bot, update['my_chat_member'])

    def _handle_message(self, bot, message):
        """Handle incoming message"""
        Chat = request.env['telegram.bot.chat'].sudo()
        Message = request.env['telegram.bot.message'].sudo()

        # Get chat info
        chat_data = message.get('chat', {})
        telegram_chat_id = chat_data.get('id')
        user_data = message.get('from', {})

        if not telegram_chat_id:
            _logger.warning("No chat_id in message")
            return

        # Get or create chat (also creates res.partner for telegram user)
        chat = Chat._get_or_create_chat(bot, telegram_chat_id, user_data)

        # Log incoming message
        Message.create_from_telegram(chat, message, direction='incoming')

        # Get message text
        text = message.get('text', '')

        # Handle contact share (phone number)
        if 'contact' in message:
            contact = message['contact']
            if contact.get('phone_number'):
                phone = contact['phone_number']
                # Process phone sharing - link partners
                phone_partner = chat._handle_phone_shared(phone)

                # Send confirmation
                bot.send_message(
                    telegram_chat_id,
                    f"Дякую! Ваш номер {phone} збережено. 📞\n\nТепер ми зможемо зв'язатися з вами.",
                    reply_markup={'remove_keyboard': True}
                )

                # Reset waiting state if was waiting for phone
                if chat.waiting_for_field == 'phone':
                    chat.state = 'active'
                    chat.waiting_for_field = False
                return

        # Check if waiting for input
        if chat.state == 'waiting_input' and chat.waiting_for_field:
            chat.handle_input(text)
            return

        # Find matching command
        commands = bot.command_ids.filtered(lambda c: c.active)

        for cmd in commands.sorted('sequence'):
            if cmd.matches_message(text):
                cmd.execute(chat, message_text=text)
                return

        # No command matched - check for 'any' trigger
        any_cmd = commands.filtered(lambda c: c.trigger_type == 'any')
        if any_cmd:
            any_cmd[0].execute(chat, message_text=text)
            return

        # No command matched at all - forward to webhook if configured
        if bot.fallback_webhook_url:
            bot.forward_to_webhook(chat, text, message)
        elif not chat.phone:
            # No webhook - ask for phone if not provided yet
            chat.ask_for_phone()
        else:
            # User has phone, just acknowledge the message
            bot.send_message(
                telegram_chat_id,
                "Дякую за повідомлення! Наш менеджер зв'яжеться з вами найближчим часом. 🙏"
            )

    def _handle_callback(self, bot, callback_query):
        """Handle callback query (button click)"""
        Chat = request.env['telegram.bot.chat'].sudo()
        Message = request.env['telegram.bot.message'].sudo()

        callback_id = callback_query.get('id')
        callback_data = callback_query.get('data', '')
        user_data = callback_query.get('from', {})

        message = callback_query.get('message', {})
        chat_data = message.get('chat', {})
        telegram_chat_id = chat_data.get('id')

        if not telegram_chat_id:
            _logger.warning("No chat_id in callback query")
            return

        # Get or create chat
        chat = Chat._get_or_create_chat(bot, telegram_chat_id, user_data)

        # Log callback
        Message.create_callback(chat, callback_data)

        # Answer callback query (remove loading indicator)
        bot.answer_callback_query(callback_id)

        # Handle command callback (cmd:command_name)
        if callback_data.startswith('cmd:'):
            command_name = callback_data[4:]
            cmd = bot.command_ids.filtered(
                lambda c: c.active and c.name == command_name
            )
            if cmd:
                cmd[0].execute(chat, callback_data=callback_data)
                return

        # Find matching callback command
        commands = bot.command_ids.filtered(
            lambda c: c.active and c.trigger_type == 'callback'
        )

        for cmd in commands.sorted('sequence'):
            if cmd.matches_callback(callback_data):
                cmd.execute(chat, callback_data=callback_data)
                return

    def _handle_chat_member(self, bot, chat_member_update):
        """Handle chat member status change (bot blocked/unblocked)"""
        Chat = request.env['telegram.bot.chat'].sudo()

        chat_data = chat_member_update.get('chat', {})
        telegram_chat_id = chat_data.get('id')
        new_status = chat_member_update.get('new_chat_member', {}).get('status')

        if not telegram_chat_id:
            return

        chat = Chat.search([
            ('bot_id', '=', bot.id),
            ('telegram_chat_id', '=', str(telegram_chat_id)),
        ], limit=1)

        if chat:
            if new_status == 'kicked':
                chat.state = 'blocked'
                _logger.info(f"Chat {telegram_chat_id} blocked bot")
            elif new_status == 'member':
                chat.state = 'active'
                _logger.info(f"Chat {telegram_chat_id} unblocked bot")

    @http.route(
        '/telegram/test/<int:bot_id>',
        type='http',
        auth='user',
        methods=['GET'],
    )
    def test_bot(self, bot_id, **kwargs):
        """Test endpoint to verify bot configuration"""
        bot = request.env['telegram.bot'].browse(bot_id)

        if not bot.exists():
            return request.make_response('Bot not found', status=404)

        try:
            result = bot._call_telegram_api('getMe')
            return request.make_response(
                f"Bot @{result.get('username')} is working!\n"
                f"Webhook URL: {bot.webhook_url}",
                headers=[('Content-Type', 'text/plain')],
            )
        except Exception as e:
            return request.make_response(
                f"Error: {str(e)}",
                status=500,
                headers=[('Content-Type', 'text/plain')],
            )
