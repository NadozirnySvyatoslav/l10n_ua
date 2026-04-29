import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class TelegramBotCommand(models.Model):
    _name = 'telegram.bot.command'
    _description = 'Telegram Bot Command'
    _order = 'sequence, id'

    bot_id = fields.Many2one(
        'telegram.bot',
        string='Bot',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(
        string='Command',
        required=True,
        help='Command name without / (e.g., "start", "help")',
    )
    description = fields.Char(
        string='Description',
        help='Description shown in Telegram command menu',
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    show_in_menu = fields.Boolean(
        string='Show in Menu',
        default=True,
        help='Show this command in Telegram command menu',
    )

    # Responses
    response_ids = fields.One2many(
        'telegram.bot.response',
        'command_id',
        string='Responses',
    )

    # CRM
    create_lead = fields.Boolean(
        string='Create Lead',
        default=False,
        help='Create a CRM lead when this command is triggered',
    )
    lead_name_template = fields.Char(
        string='Lead Name Template',
        default='Lead from {first_name}',
        help='Template for lead name. Variables: {first_name}, {last_name}, {user_name}, {chat_id}',
    )

    # Trigger settings
    trigger_type = fields.Selection([
        ('command', 'Command'),
        ('keyword', 'Keyword'),
        ('any', 'Any Message'),
        ('callback', 'Callback Data'),
    ], string='Trigger Type', default='command')

    trigger_keywords = fields.Text(
        string='Trigger Keywords',
        help='Keywords that trigger this command (one per line)',
    )
    callback_data = fields.Char(
        string='Callback Data',
        help='Callback data pattern for button callbacks',
    )

    @api.constrains('name')
    def _check_name(self):
        for cmd in self:
            if cmd.trigger_type == 'command':
                # Command names should be lowercase alphanumeric
                if not cmd.name.replace('_', '').isalnum():
                    raise ValidationError(
                        _("Command name should contain only letters, numbers, and underscores")
                    )
                if cmd.name.startswith('/'):
                    raise ValidationError(
                        _("Command name should not start with /")
                    )

    def get_display_name(self):
        """Get command display name with /"""
        self.ensure_one()
        if self.trigger_type == 'command':
            return f"/{self.name}"
        return self.name

    def execute(self, chat, message_text=None, callback_data=None):
        """Execute command and send responses"""
        self.ensure_one()

        context_data = chat._get_context_data()
        context_data.update({
            'first_name': chat.first_name or '',
            'last_name': chat.last_name or '',
            'user_name': chat.user_name or '',
            'full_name': f"{chat.first_name or ''} {chat.last_name or ''}".strip(),
            'chat_id': chat.telegram_chat_id,
            'message': message_text or '',
        })

        _logger.info(f"Executing command {self.name} for chat {chat.telegram_chat_id}")

        # Create lead if configured
        if self.create_lead or (self.bot_id.create_leads and self.trigger_type == 'command'):
            self._create_lead(chat, context_data)

        # Execute all responses in sequence
        for response in self.response_ids.sorted('sequence'):
            response.send(chat, context_data)

        # Update chat state
        if self.response_ids:
            last_response = self.response_ids.sorted('sequence')[-1]
            if last_response.input_field:
                chat.state = 'waiting_input'
                chat.current_command_id = self.id
                chat.waiting_for_field = last_response.input_field

    def _create_lead(self, chat, context_data):
        """Create a CRM lead from chat"""
        self.ensure_one()

        # Check if lead already exists for this chat
        existing_lead = self.env['crm.lead'].search([
            ('telegram_chat_id', '=', chat.id),
            ('type', '=', 'lead'),
        ], limit=1)

        if existing_lead:
            _logger.info(f"Lead already exists for chat {chat.telegram_chat_id}")
            return existing_lead

        # Format lead name
        lead_name = self.lead_name_template or 'Lead from {first_name}'
        try:
            lead_name = lead_name.format(**context_data)
        except KeyError:
            pass

        lead_vals = {
            'name': lead_name,
            'telegram_chat_id': chat.id,
            'contact_name': context_data.get('full_name'),
            'phone': chat.phone,
            'description': f"Lead created from Telegram bot @{self.bot_id.username}",
        }

        if self.bot_id.default_lead_team_id:
            lead_vals['team_id'] = self.bot_id.default_lead_team_id.id
        if self.bot_id.default_lead_user_id:
            lead_vals['user_id'] = self.bot_id.default_lead_user_id.id

        # Link to partner if exists
        if chat.partner_id:
            lead_vals['partner_id'] = chat.partner_id.id

        # Run lead creation as the Administrator: the webhook controller uses
        # ``auth='public'`` which gives a Public User in env, but creating a
        # crm.lead requires CRM/currency access. ``base.user_admin`` is granted
        # Telegram Bot Manager via ``data/security_assignments.xml`` so it has
        # full access to bot models too.
        admin = self.env.ref('base.user_admin')
        lead = self.env['crm.lead'].with_user(admin).create(lead_vals)
        _logger.info(f"Created lead {lead.id} for chat {chat.telegram_chat_id}")

        return lead

    def matches_message(self, text):
        """Check if this command matches the given message"""
        self.ensure_one()

        if not text:
            return False

        text = text.strip()

        if self.trigger_type == 'command':
            # Match /command or /command@botname
            cmd_text = f"/{self.name}"
            if text == cmd_text or text.startswith(f"{cmd_text} ") or text.startswith(f"{cmd_text}@"):
                return True

        elif self.trigger_type == 'keyword':
            if self.trigger_keywords:
                keywords = [k.strip().lower() for k in self.trigger_keywords.split('\n') if k.strip()]
                text_lower = text.lower()
                for keyword in keywords:
                    if keyword in text_lower:
                        return True

        elif self.trigger_type == 'any':
            return True

        return False

    def matches_callback(self, callback_data):
        """Check if this command matches the given callback data"""
        self.ensure_one()

        if self.trigger_type != 'callback':
            return False

        if self.callback_data:
            # Simple pattern matching (can be extended)
            if self.callback_data == callback_data:
                return True
            if self.callback_data.endswith('*') and callback_data.startswith(self.callback_data[:-1]):
                return True

        return False
