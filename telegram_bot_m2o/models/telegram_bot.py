import json
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramBot(models.Model):
    _name = 'telegram.bot'
    _description = 'Telegram Bot'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Bot Name',
        required=True,
        tracking=True,
    )
    token = fields.Char(
        string='Bot Token',
        required=True,
        help='Token from @BotFather',
    )
    username = fields.Char(
        string='Bot Username',
        readonly=True,
        help='Retrieved from Telegram API',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
    ], string='Status', default='draft', tracking=True)

    webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_webhook_url',
        store=True,
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        readonly=True,
    )
    last_error = fields.Text(
        string='Last Error',
        readonly=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    # CRM Integration
    create_leads = fields.Boolean(
        string='Create Leads',
        default=False,
        help='Automatically create CRM leads from conversations',
    )
    default_lead_team_id = fields.Many2one(
        'crm.team',
        string='Sales Team',
        help='Default team for created leads',
    )
    default_lead_user_id = fields.Many2one(
        'res.users',
        string='Salesperson',
        help='Default salesperson for created leads',
    )

    # Fallback webhook for unmatched messages
    fallback_webhook_url = fields.Char(
        string='Fallback Webhook URL',
        help='URL to forward messages that do not match any command (e.g., n8n webhook)',
    )

    # Related records
    command_ids = fields.One2many(
        'telegram.bot.command',
        'bot_id',
        string='Commands',
    )
    chat_ids = fields.One2many(
        'telegram.bot.chat',
        'bot_id',
        string='Chats',
    )

    # Statistics
    command_count = fields.Integer(
        compute='_compute_counts',
        string='Commands',
    )
    chat_count = fields.Integer(
        compute='_compute_counts',
        string='Chats',
    )
    message_count = fields.Integer(
        compute='_compute_counts',
        string='Messages',
    )
    lead_count = fields.Integer(
        compute='_compute_counts',
        string='Leads',
    )

    @api.depends('token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for bot in self:
            if bot.token:
                # Use token hash for URL to avoid exposing full token
                token_hash = bot.token[-10:] if len(bot.token) > 10 else bot.token
                bot.webhook_url = f"{base_url}/telegram/webhook/{token_hash}"
            else:
                bot.webhook_url = False

    def _compute_counts(self):
        for bot in self:
            bot.command_count = len(bot.command_ids)
            bot.chat_count = len(bot.chat_ids)
            bot.message_count = self.env['telegram.bot.message'].search_count([
                ('chat_id.bot_id', '=', bot.id)
            ])
            bot.lead_count = self.env['crm.lead'].search_count([
                ('telegram_chat_id.bot_id', '=', bot.id)
            ])

    def _call_telegram_api(self, method, data=None, files=None):
        """Call Telegram Bot API"""
        self.ensure_one()
        url = TELEGRAM_API_URL.format(token=self.token, method=method)

        try:
            if files:
                response = requests.post(url, data=data, files=files, timeout=30)
            else:
                response = requests.post(url, json=data, timeout=30)

            result = response.json()

            if not result.get('ok'):
                error_msg = result.get('description', 'Unknown error')
                _logger.error(f"Telegram API error: {error_msg}")
                raise UserError(_("Telegram API error: %s") % error_msg)

            return result.get('result')

        except requests.exceptions.RequestException as e:
            _logger.error(f"Telegram API request failed: {e}")
            raise UserError(_("Failed to connect to Telegram: %s") % str(e))

    def action_validate_token(self):
        """Validate token and get bot info"""
        self.ensure_one()
        try:
            result = self._call_telegram_api('getMe')
            self.username = result.get('username')
            self.last_error = False
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Bot @%s is valid!') % self.username,
                    'type': 'success',
                }
            }
        except Exception as e:
            self.last_error = str(e)
            self.state = 'error'
            raise

    def action_start(self):
        """Start the bot (set webhook)"""
        self.ensure_one()

        if not self.username:
            self.action_validate_token()

        # Generate webhook secret
        import secrets
        self.webhook_secret = secrets.token_hex(32)

        # Set webhook
        webhook_data = {
            'url': self.webhook_url,
            'secret_token': self.webhook_secret,
            'allowed_updates': ['message', 'callback_query', 'my_chat_member'],
        }

        try:
            self._call_telegram_api('setWebhook', webhook_data)
            self._sync_commands()
            self.state = 'running'
            self.last_error = False

            self.message_post(body=_("Bot started and webhook configured"))

        except Exception as e:
            self.state = 'error'
            self.last_error = str(e)
            raise

    def action_stop(self):
        """Stop the bot (delete webhook)"""
        self.ensure_one()

        try:
            self._call_telegram_api('deleteWebhook')
            self.state = 'stopped'
            self.webhook_secret = False

            self.message_post(body=_("Bot stopped"))

        except Exception as e:
            self.last_error = str(e)
            raise

    def action_restart(self):
        """Restart the bot"""
        self.action_stop()
        self.action_start()

    def _sync_commands(self):
        """Sync commands with Telegram"""
        self.ensure_one()

        commands = []
        for cmd in self.command_ids.filtered(lambda c: c.active and c.show_in_menu):
            commands.append({
                'command': cmd.name,
                'description': cmd.description or cmd.name,
            })

        if commands:
            self._call_telegram_api('setMyCommands', {'commands': commands})
            _logger.info(f"Synced {len(commands)} commands for bot {self.name}")

    def action_sync_commands(self):
        """Manual command sync"""
        self.ensure_one()
        self._sync_commands()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Commands synced with Telegram'),
                'type': 'success',
            }
        }

    def send_message(self, chat_id, text, reply_markup=None, parse_mode='HTML', log_message=True):
        """Send a text message"""
        self.ensure_one()

        data = {
            'chat_id': chat_id,
            'text': text,
        }
        if parse_mode:
            data['parse_mode'] = parse_mode

        if reply_markup:
            data['reply_markup'] = reply_markup

        result = self._call_telegram_api('sendMessage', data)

        # Log outgoing message
        if log_message and result:
            self._log_outgoing_message(chat_id, 'text', text=text, telegram_message_id=result.get('message_id'))

        return result

    def _log_outgoing_message(self, chat_id, message_type, text=None, caption=None,
                              telegram_message_id=None, att_bytes=None, att_name=None):
        """Log outgoing message and post to partner chatter"""
        Chat = self.env['telegram.bot.chat']
        Message = self.env['telegram.bot.message']

        chat = Chat.search([
            ('bot_id', '=', self.id),
            ('telegram_chat_id', '=', str(chat_id)),
        ], limit=1)

        if not chat:
            return

        vals = {
            'chat_id': chat.id,
            'direction': 'outgoing',
            'message_type': message_type,
            'text': text,
            'caption': caption,
            'telegram_message_id': str(telegram_message_id) if telegram_message_id else '',
        }
        if message_type == 'document' and att_name:
            vals['file_name'] = att_name

        message = Message.create(vals)
        message._post_to_partner_chatter(att_bytes=att_bytes, att_name=att_name)

        return message

    def send_photo(self, chat_id, photo, caption=None, reply_markup=None, log_message=True,
                   filename='image.jpg', parse_mode='HTML'):
        """Send a photo"""
        self.ensure_one()

        import base64

        data = {
            'chat_id': chat_id,
        }
        if caption:
            data['caption'] = caption
            if parse_mode:
                data['parse_mode'] = parse_mode
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)

        # Decode base64 image
        photo_data = base64.b64decode(photo)
        files = {'photo': (filename or 'image.jpg', photo_data, 'image/jpeg')}

        result = self._call_telegram_api('sendPhoto', data, files=files)

        # Log outgoing message
        if log_message and result:
            self._log_outgoing_message(chat_id, 'photo', caption=caption,
                                       telegram_message_id=result.get('message_id'),
                                       att_bytes=photo_data, att_name=(filename or 'image.jpg'))

        return result

    def send_document(self, chat_id, document, filename, caption=None, reply_markup=None,
                      log_message=True, parse_mode='HTML'):
        """Send a document"""
        self.ensure_one()

        import base64

        data = {
            'chat_id': chat_id,
        }
        if caption:
            data['caption'] = caption
            if parse_mode:
                data['parse_mode'] = parse_mode
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)

        # Decode base64 document
        doc_data = base64.b64decode(document)
        files = {'document': (filename, doc_data, 'application/octet-stream')}

        result = self._call_telegram_api('sendDocument', data, files=files)

        # Log outgoing message
        if log_message and result:
            self._log_outgoing_message(chat_id, 'document', caption=caption,
                                       telegram_message_id=result.get('message_id'),
                                       att_bytes=doc_data, att_name=filename)

        return result

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        """Answer a callback query"""
        self.ensure_one()

        data = {
            'callback_query_id': callback_query_id,
        }
        if text:
            data['text'] = text
            data['show_alert'] = show_alert

        return self._call_telegram_api('answerCallbackQuery', data)

    def forward_to_webhook(self, chat, message_text, message_data=None):
        """Forward message to fallback webhook (e.g., n8n)"""
        self.ensure_one()

        if not self.fallback_webhook_url:
            return False

        payload = {
            'bot_id': self.id,
            'bot_name': self.name,
            'bot_username': self.username,
            'chat_id': chat.telegram_chat_id,
            'user_id': chat.telegram_user_id,
            'user_name': chat.user_name,
            'first_name': chat.first_name,
            'last_name': chat.last_name,
            'phone': chat.phone,
            'message_text': message_text,
            'partner_id': chat.partner_id.id if chat.partner_id else None,
            'chat_record_id': chat.id,
            'raw_message': message_data,
        }

        # recent chat history for LLM context (last 15 messages, oldest first)
        try:
            recent = self.env['telegram.bot.message'].search(
                [('chat_id', '=', chat.id)], order='id desc', limit=15)
            payload['history'] = [{
                'direction': m.direction,
                'text': m.text or m.callback_data or '',
                'date': m.create_date and m.create_date.isoformat() or '',
            } for m in recent.sorted('id')]
        except Exception as e:
            _logger.warning(f"Could not build chat history: {e}")
            payload['history'] = []

        try:
            response = requests.post(
                self.fallback_webhook_url,
                json=payload,
                timeout=10,
            )
            _logger.info(f"Forwarded message to webhook: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            _logger.error(f"Failed to forward to webhook: {e}")
            return False

    def action_view_chats(self):
        """Open chats view"""
        self.ensure_one()
        return {
            'name': _('Chats'),
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.bot.chat',
            'view_mode': 'list,form',
            'domain': [('bot_id', '=', self.id)],
            'context': {'default_bot_id': self.id},
        }

    def action_view_leads(self):
        """Open leads view"""
        self.ensure_one()
        return {
            'name': _('Leads from Telegram'),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'list,kanban,form',
            'domain': [('telegram_chat_id.bot_id', '=', self.id)],
        }

    def action_create_default_commands(self):
        """Create default bot commands"""
        self.ensure_one()
        Command = self.env['telegram.bot.command']
        Response = self.env['telegram.bot.response']
        Button = self.env['telegram.bot.button']

        # /start command
        start_cmd = Command.create({
            'bot_id': self.id,
            'name': 'start',
            'description': 'Start conversation',
            'trigger_type': 'command',
            'show_in_menu': True,
            'sequence': 10,
        })

        # Add company logo if available
        company = self.company_id or self.env.company
        if company.logo:
            Response.create({
                'command_id': start_cmd.id,
                'sequence': 1,
                'response_type': 'image',
                'image': company.logo,
            })
            text_sequence = 2
        else:
            text_sequence = 1

        start_resp = Response.create({
            'command_id': start_cmd.id,
            'sequence': text_sequence,
            'response_type': 'text',
            'text': "Hello, {first_name}! 👋\n\nHow can I help you?",
            'parse_mode': 'HTML',
            'buttons_per_row': 2,
        })
        Button.create([
            {'response_id': start_resp.id, 'label': '💰 Prices', 'button_type': 'callback', 'callback_data': 'cmd:price', 'sequence': 1},
            {'response_id': start_resp.id, 'label': '📋 Services', 'button_type': 'callback', 'callback_data': 'cmd:services', 'sequence': 2},
            {'response_id': start_resp.id, 'label': '📞 Contact', 'button_type': 'callback', 'callback_data': 'cmd:contact', 'sequence': 3},
            {'response_id': start_resp.id, 'label': '❓ Help', 'button_type': 'callback', 'callback_data': 'cmd:help', 'sequence': 4},
        ])

        # /price command
        price_cmd = Command.create({
            'bot_id': self.id,
            'name': 'price',
            'description': 'Pricing information',
            'trigger_type': 'command',
            'show_in_menu': True,
            'sequence': 20,
        })
        Response.create({
            'command_id': price_cmd.id,
            'sequence': 1,
            'response_type': 'text',
            'text': "💰 <b>Our Prices</b>\n\nContact us for pricing details.",
            'parse_mode': 'HTML',
        })

        # /services command
        services_cmd = Command.create({
            'bot_id': self.id,
            'name': 'services',
            'description': 'Our services',
            'trigger_type': 'command',
            'show_in_menu': True,
            'sequence': 30,
        })
        Response.create({
            'command_id': services_cmd.id,
            'sequence': 1,
            'response_type': 'text',
            'text': "📋 <b>Our Services</b>\n\n• Service 1\n• Service 2\n• Service 3",
            'parse_mode': 'HTML',
        })

        # /contact command
        contact_cmd = Command.create({
            'bot_id': self.id,
            'name': 'contact',
            'description': 'Contact information',
            'trigger_type': 'command',
            'show_in_menu': True,
            'create_lead': True,
            'sequence': 40,
        })
        contact_resp = Response.create({
            'command_id': contact_cmd.id,
            'sequence': 1,
            'response_type': 'text',
            'text': "📞 <b>Contact Us</b>\n\nShare your phone number and we'll get back to you!",
            'parse_mode': 'HTML',
            'buttons_per_row': 1,
        })
        Button.create({
            'response_id': contact_resp.id,
            'label': '📱 Share Phone',
            'button_type': 'contact',
            'sequence': 1,
        })

        # /help command
        help_cmd = Command.create({
            'bot_id': self.id,
            'name': 'help',
            'description': 'Help',
            'trigger_type': 'command',
            'show_in_menu': True,
            'sequence': 50,
        })
        Response.create({
            'command_id': help_cmd.id,
            'sequence': 1,
            'response_type': 'text',
            'text': "❓ <b>Available Commands</b>\n\n/start - Start conversation\n/price - Pricing info\n/services - Our services\n/contact - Contact us\n/help - This help",
            'parse_mode': 'HTML',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.bot',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
