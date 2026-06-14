import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TelegramBotChat(models.Model):
    _name = 'telegram.bot.chat'
    _description = 'Telegram Bot Chat'
    _inherit = ['mail.thread']
    _order = 'last_message_date desc'
    _rec_name = 'display_name'

    bot_id = fields.Many2one(
        'telegram.bot',
        string='Bot',
        required=True,
        ondelete='cascade',
    )
    telegram_chat_id = fields.Char(
        string='Chat ID',
        required=True,
        index=True,
    )
    telegram_user_id = fields.Char(
        string='User ID',
        index=True,
    )
    chat_type = fields.Selection([
        ('private', 'Private'),
        ('group', 'Group'),
        ('supergroup', 'Supergroup'),
        ('channel', 'Channel'),
    ], string='Chat Type', default='private')

    # User info
    user_name = fields.Char(
        string='Username',
        help='Telegram username without @',
    )
    first_name = fields.Char(
        string='First Name',
    )
    last_name = fields.Char(
        string='Last Name',
    )
    phone = fields.Char(
        string='Phone',
    )
    language_code = fields.Char(
        string='Language',
    )

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True,
    )

    # State
    state = fields.Selection([
        ('active', 'Active'),
        ('waiting_input', 'Waiting for Input'),
        ('blocked', 'Blocked'),
    ], string='State', default='active')

    current_command_id = fields.Many2one(
        'telegram.bot.command',
        string='Current Command',
        help='Command currently being processed in conversation',
    )
    waiting_for_field = fields.Char(
        string='Waiting for Field',
        help='Field name we are waiting user input for',
    )
    context_data = fields.Text(
        string='Context Data',
        default='{}',
        help='JSON data collected during conversation',
    )

    # Relations
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        help='Linked Odoo contact',
    )
    lead_ids = fields.One2many(
        'crm.lead',
        'telegram_chat_id',
        string='Leads',
    )
    message_ids = fields.One2many(
        'telegram.bot.message',
        'chat_id',
        string='Messages',
    )

    # Stats
    message_count = fields.Integer(
        compute='_compute_message_count',
        string='Messages',
    )
    last_message_date = fields.Datetime(
        string='Last Message',
    )
    first_message_date = fields.Datetime(
        string='First Message',
    )

    _sql_constraints = [
        ('unique_chat', 'UNIQUE(bot_id, telegram_chat_id)',
         'Chat ID must be unique per bot'),
    ]

    @api.depends('first_name', 'last_name', 'user_name', 'telegram_chat_id')
    def _compute_display_name(self):
        for chat in self:
            if chat.first_name or chat.last_name:
                chat.display_name = f"{chat.first_name or ''} {chat.last_name or ''}".strip()
            elif chat.user_name:
                chat.display_name = f"@{chat.user_name}"
            else:
                chat.display_name = f"Chat {chat.telegram_chat_id}"

    def _compute_message_count(self):
        for chat in self:
            chat.message_count = len(chat.message_ids)

    def _get_context_data(self):
        """Get context data as dict"""
        self.ensure_one()
        try:
            return json.loads(self.context_data or '{}')
        except json.JSONDecodeError:
            return {}

    def _set_context_data(self, data):
        """Set context data from dict"""
        self.ensure_one()
        self.context_data = json.dumps(data, ensure_ascii=False)

    def _update_context_data(self, key, value):
        """Update a single key in context data"""
        self.ensure_one()
        data = self._get_context_data()
        data[key] = value
        self._set_context_data(data)

    def _clear_context(self):
        """Clear conversation context"""
        self.ensure_one()
        self.context_data = '{}'
        self.state = 'active'
        self.current_command_id = False
        self.waiting_for_field = False

    @api.model
    def _get_or_create_chat(self, bot, telegram_chat_id, user_data=None):
        """Get existing chat or create new one"""
        chat = self.search([
            ('bot_id', '=', bot.id),
            ('telegram_chat_id', '=', str(telegram_chat_id)),
        ], limit=1)

        is_new = False
        if not chat:
            is_new = True
            vals = {
                'bot_id': bot.id,
                'telegram_chat_id': str(telegram_chat_id),
                'first_message_date': fields.Datetime.now(),
            }
            if user_data:
                vals.update({
                    'telegram_user_id': str(user_data.get('id', '')),
                    'user_name': user_data.get('username'),
                    'first_name': user_data.get('first_name'),
                    'last_name': user_data.get('last_name'),
                    'language_code': user_data.get('language_code'),
                })

            chat = self.create(vals)
            _logger.info(f"Created new chat {telegram_chat_id} for bot {bot.name}")

        elif user_data:
            # Update user info if changed
            update_vals = {}
            if user_data.get('first_name') and user_data['first_name'] != chat.first_name:
                update_vals['first_name'] = user_data['first_name']
            if user_data.get('last_name') and user_data['last_name'] != chat.last_name:
                update_vals['last_name'] = user_data['last_name']
            if user_data.get('username') and user_data['username'] != chat.user_name:
                update_vals['user_name'] = user_data['username']

            if update_vals:
                chat.write(update_vals)

        # Create/update res.partner for telegram user
        if user_data and not chat.partner_id:
            chat._create_telegram_partner(user_data)

        return chat

    def _create_telegram_partner(self, user_data):
        """Create res.partner from telegram user data"""
        self.ensure_one()
        Partner = self.env['res.partner']

        telegram_user_id = str(user_data.get('id', ''))

        # Check if partner with this telegram_id exists
        existing = Partner.search([
            ('telegram_id', '=', telegram_user_id)
        ], limit=1)

        if existing:
            self.partner_id = existing
            return existing

        # Build partner name with telegram indicator
        first_name = user_data.get('first_name', '')
        last_name = user_data.get('last_name', '')
        username = user_data.get('username', '')

        # Build name: "FirstName LastName (@username)" or "@username" or "Telegram ID"
        name_parts = []
        if first_name:
            name_parts.append(first_name)
        if last_name:
            name_parts.append(last_name)

        if name_parts and username:
            name = f"{' '.join(name_parts)} (@{username})"
        elif name_parts:
            name = f"{' '.join(name_parts)} [Telegram]"
        elif username:
            name = f"@{username}"
        else:
            name = f"Telegram {telegram_user_id}"

        partner_vals = {
            'name': name,
            'telegram_id': telegram_user_id,
            'comment': f"Created from Telegram bot @{self.bot_id.username or 'unknown'}",
        }

        if username:
            partner_vals['telegram_username'] = username

        partner = Partner.create(partner_vals)
        self.partner_id = partner
        _logger.info(f"Created partner {partner.name} for telegram user {telegram_user_id}")

        return partner

    def _handle_phone_shared(self, phone_number):
        """Handle when user shares their phone number"""
        self.ensure_one()
        Partner = self.env['res.partner']

        # Normalize phone
        phone = phone_number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not phone.startswith('+'):
            phone = '+' + phone

        self.phone = phone

        # Search for partner with this phone
        phone_partner = Partner.search([
            ('phone', 'ilike', phone[-10:]),
        ], limit=1)

        if not phone_partner:
            # Create new partner with phone
            phone_partner = Partner.create({
                'name': self.display_name or f"Contact {phone}",
                'phone': phone,
                'comment': f"Created from Telegram phone share",
            })
            _logger.info(f"Created phone partner {phone_partner.name} with phone {phone}")

        # Link telegram partner to phone partner
        if self.partner_id and self.partner_id.id != phone_partner.id:
            # Update telegram partner to have phone partner as parent
            self.partner_id.write({
                'parent_id': phone_partner.id,
                'phone': phone,
            })
            _logger.info(f"Linked telegram partner {self.partner_id.name} to phone partner {phone_partner.name}")
        elif not self.partner_id:
            # If no telegram partner, use phone partner directly
            self.partner_id = phone_partner

        return phone_partner

    def ask_for_phone(self):
        """Send message asking user to share phone"""
        self.ensure_one()

        keyboard = {
            'keyboard': [[{
                'text': '📱 Поділитись номером телефону',
                'request_contact': True
            }]],
            'resize_keyboard': True,
            'one_time_keyboard': True
        }

        self.bot_id.send_message(
            self.telegram_chat_id,
            "Будь ласка, поділіться вашим номером телефону для зв'язку:",
            reply_markup=keyboard
        )

    def handle_input(self, text):
        """Handle user input when waiting for data"""
        self.ensure_one()

        if self.state != 'waiting_input' or not self.waiting_for_field:
            return False

        # Save input to context
        self._update_context_data(self.waiting_for_field, text)

        # Special handling for phone
        if self.waiting_for_field == 'phone':
            self.phone = text

        # Reset state
        field = self.waiting_for_field
        command = self.current_command_id
        self.state = 'active'
        self.waiting_for_field = False

        # Find next response that needs to be sent
        if command:
            responses = command.response_ids.sorted('sequence')
            found_current = False
            for response in responses:
                if response.input_field == field:
                    found_current = True
                    continue
                if found_current:
                    # Send next response
                    context_data = self._get_context_data()
                    context_data.update({
                        'first_name': self.first_name or '',
                        'last_name': self.last_name or '',
                        'user_name': self.user_name or '',
                        'full_name': f"{self.first_name or ''} {self.last_name or ''}".strip(),
                    })
                    response.send(self, context_data)
                    return True

            # If we processed all responses and there's a next command
            self.current_command_id = False

        return True

    def action_view_messages(self):
        """Open messages view"""
        self.ensure_one()
        return {
            'name': _('Messages'),
            'type': 'ir.actions.act_window',
            'res_model': 'telegram.bot.message',
            'view_mode': 'list,form',
            'domain': [('chat_id', '=', self.id)],
            'context': {'default_chat_id': self.id},
        }

    def action_create_lead(self):
        """Manually create a lead from this chat"""
        self.ensure_one()

        context_data = self._get_context_data()
        context_data.update({
            'first_name': self.first_name or '',
            'last_name': self.last_name or '',
            'user_name': self.user_name or '',
            'full_name': f"{self.first_name or ''} {self.last_name or ''}".strip(),
        })

        lead_name = f"Lead from {context_data.get('full_name') or self.user_name or self.telegram_chat_id}"

        lead = self.env['crm.lead'].create({
            'name': lead_name,
            'telegram_chat_id': self.id,
            'contact_name': context_data.get('full_name'),
            'phone': self.phone,
            'description': f"Manually created from Telegram chat\nBot: @{self.bot_id.username}",
            'team_id': self.bot_id.default_lead_team_id.id if self.bot_id.default_lead_team_id else False,
            'user_id': self.bot_id.default_lead_user_id.id if self.bot_id.default_lead_user_id else False,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': lead.id,
        }

    def action_link_partner(self):
        """Open wizard to link contact"""
        self.ensure_one()
        return {
            'name': _('Link Contact'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'list',
            'target': 'new',
            'context': {
                'default_phone': self.phone,
                'default_name': self.display_name,
            },
        }


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    telegram_chat_id = fields.Many2one(
        'telegram.bot.chat',
        string='Telegram Chat',
        help='Related Telegram chat',
    )


class ResPartner(models.Model):
    _inherit = 'res.partner'

    telegram_id = fields.Char(
        string='Telegram ID',
        index=True,
        help='Telegram user ID',
    )
    telegram_username = fields.Char(
        string='Telegram Username',
        help='Telegram username without @',
    )
    telegram_chat_ids = fields.One2many(
        'telegram.bot.chat', 'partner_id', string='Telegram Chats',
    )
    telegram_chat_count = fields.Integer(
        string='Telegram Chats', compute='_compute_telegram_chat_count',
    )

    @api.depends('telegram_chat_ids')
    def _compute_telegram_chat_count(self):
        for partner in self:
            partner.telegram_chat_count = len(partner.telegram_chat_ids)

    def action_open_telegram_send(self):
        """Open the wizard to send a Telegram message to this contact."""
        self.ensure_one()
        chat = self.env['telegram.bot.chat'].search(
            [('partner_id', '=', self.id), ('state', '!=', 'blocked')],
            order='last_message_date desc, id desc', limit=1,
        ) or self.env['telegram.bot.chat'].search(
            [('partner_id', '=', self.id)], order='id desc', limit=1,
        )
        if not chat:
            raise UserError(_("This contact has no linked Telegram chat."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Send Telegram message"),
            'res_model': 'telegram.send.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_chat_id': chat.id,
            },
        }
