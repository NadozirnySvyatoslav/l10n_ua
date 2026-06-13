import logging
from markupsafe import Markup, escape
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class TelegramBotMessage(models.Model):
    _name = 'telegram.bot.message'
    _description = 'Telegram Bot Message'
    _order = 'timestamp desc'

    chat_id = fields.Many2one(
        'telegram.bot.chat',
        string='Chat',
        required=True,
        ondelete='cascade',
        index=True,
    )
    bot_id = fields.Many2one(
        related='chat_id.bot_id',
        store=True,
    )

    direction = fields.Selection([
        ('incoming', 'Incoming'),
        ('outgoing', 'Outgoing'),
    ], string='Direction', required=True)

    telegram_message_id = fields.Char(
        string='Message ID',
        index=True,
    )

    message_type = fields.Selection([
        ('text', 'Text'),
        ('photo', 'Photo'),
        ('document', 'Document'),
        ('video', 'Video'),
        ('voice', 'Voice'),
        ('audio', 'Audio'),
        ('sticker', 'Sticker'),
        ('location', 'Location'),
        ('contact', 'Contact'),
        ('callback', 'Callback'),
    ], string='Message Type', default='text')

    text = fields.Text(
        string='Text',
    )
    caption = fields.Text(
        string='Caption',
    )

    # Media
    file_id = fields.Char(
        string='File ID',
        help='Telegram file_id for media',
    )
    file_name = fields.Char(
        string='File Name',
    )
    file = fields.Binary(
        string='File',
    )

    # Location
    latitude = fields.Float(
        string='Latitude',
    )
    longitude = fields.Float(
        string='Longitude',
    )

    # Contact
    contact_phone = fields.Char(
        string='Contact Phone',
    )
    contact_name = fields.Char(
        string='Contact Name',
    )

    # Callback
    callback_data = fields.Char(
        string='Callback Data',
    )

    timestamp = fields.Datetime(
        string='Timestamp',
        default=fields.Datetime.now,
        index=True,
    )

    # Raw data for debugging
    raw_data = fields.Text(
        string='Raw Data',
        help='Original message JSON from Telegram',
    )

    def name_get(self):
        result = []
        for msg in self:
            direction = '→' if msg.direction == 'outgoing' else '←'
            text = (msg.text or msg.caption or msg.message_type)[:30]
            result.append((msg.id, f"{direction} {text}"))
        return result

    @api.model
    def create_from_telegram(self, chat, message_data, direction='incoming'):
        """Create message record from Telegram message data"""
        vals = {
            'chat_id': chat.id,
            'direction': direction,
            'telegram_message_id': str(message_data.get('message_id', '')),
            'timestamp': fields.Datetime.now(),
            'raw_data': str(message_data),
        }

        # Determine message type and extract data
        if 'text' in message_data:
            vals['message_type'] = 'text'
            vals['text'] = message_data['text']

        elif 'photo' in message_data:
            vals['message_type'] = 'photo'
            vals['caption'] = message_data.get('caption')
            # Get largest photo
            photos = message_data['photo']
            if photos:
                vals['file_id'] = photos[-1].get('file_id')

        elif 'document' in message_data:
            vals['message_type'] = 'document'
            vals['caption'] = message_data.get('caption')
            doc = message_data['document']
            vals['file_id'] = doc.get('file_id')
            vals['file_name'] = doc.get('file_name')

        elif 'video' in message_data:
            vals['message_type'] = 'video'
            vals['caption'] = message_data.get('caption')
            vals['file_id'] = message_data['video'].get('file_id')

        elif 'voice' in message_data:
            vals['message_type'] = 'voice'
            vals['file_id'] = message_data['voice'].get('file_id')

        elif 'audio' in message_data:
            vals['message_type'] = 'audio'
            vals['caption'] = message_data.get('caption')
            vals['file_id'] = message_data['audio'].get('file_id')

        elif 'sticker' in message_data:
            vals['message_type'] = 'sticker'
            vals['file_id'] = message_data['sticker'].get('file_id')

        elif 'location' in message_data:
            vals['message_type'] = 'location'
            vals['latitude'] = message_data['location'].get('latitude')
            vals['longitude'] = message_data['location'].get('longitude')

        elif 'contact' in message_data:
            vals['message_type'] = 'contact'
            contact = message_data['contact']
            vals['contact_phone'] = contact.get('phone_number')
            vals['contact_name'] = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()

            # Update chat phone
            if contact.get('phone_number'):
                chat.phone = contact['phone_number']

        # Update last message date
        chat.last_message_date = vals['timestamp']

        message = self.create(vals)

        # Post to partner's chatter if partner exists
        message._post_to_partner_chatter()

        return message

    def _post_to_partner_chatter(self, att_bytes=None, att_name=None):
        """Post telegram message to partner's chatter"""
        self.ensure_one()

        # Get partner from chat
        partner = self.chat_id.partner_id
        if not partner:
            return

        # Build message body
        direction_icon = '📤' if self.direction == 'outgoing' else '📥'
        bot_name = self.chat_id.bot_id.username or 'Telegram Bot'

        body_parts = [f"<b>{direction_icon} Telegram (@{escape(bot_name)})</b>"]

        if self.message_type == 'text' and self.text:
            body_parts.append(f"<p>{escape(self.text)}</p>")
        elif self.message_type == 'photo':
            body_parts.append("<p>📷 Photo</p>")
            if self.caption:
                body_parts.append(f"<p>{escape(self.caption)}</p>")
        elif self.message_type == 'document':
            body_parts.append(f"<p>📎 Document: {escape(self.file_name or 'file')}</p>")
            if self.caption:
                body_parts.append(f"<p>{escape(self.caption)}</p>")
        elif self.message_type == 'video':
            body_parts.append("<p>🎥 Video</p>")
            if self.caption:
                body_parts.append(f"<p>{escape(self.caption)}</p>")
        elif self.message_type == 'voice':
            body_parts.append("<p>🎤 Voice message</p>")
        elif self.message_type == 'audio':
            body_parts.append("<p>🎵 Audio</p>")
        elif self.message_type == 'sticker':
            body_parts.append("<p>🎭 Sticker</p>")
        elif self.message_type == 'location':
            body_parts.append(f"<p>📍 Location: {self.latitude}, {self.longitude}</p>")
        elif self.message_type == 'contact':
            body_parts.append(f"<p>👤 Contact: {escape(self.contact_name or '')} ({escape(self.contact_phone or '')})</p>")
        elif self.message_type == 'callback':
            body_parts.append(f"<p>🔘 Button: {escape(self.callback_data or '')}</p>")

        body = Markup('\n'.join(body_parts))

        # Post to partner's chatter with proper author
        # Use with_user(SUPERUSER_ID) to avoid user context issues in webhook
        try:
            from odoo import SUPERUSER_ID
            partner_sudo = partner.with_user(SUPERUSER_ID)

            attachments = [(att_name or 'file', att_bytes)] if att_bytes else None

            if self.direction == 'incoming':
                # Incoming message - author is the telegram user (partner)
                partner_sudo.message_post(
                    body=body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=partner.id,
                    attachments=attachments,
                )
            else:
                # Outgoing message - posted by system/bot
                partner_sudo.message_post(
                    body=body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    attachments=attachments,
                )
        except Exception as e:
            _logger.warning(f"Failed to post to partner chatter: {e}")

    @api.model
    def create_callback(self, chat, callback_data):
        """Create message record for callback query"""
        return self.create({
            'chat_id': chat.id,
            'direction': 'incoming',
            'message_type': 'callback',
            'callback_data': callback_data,
            'timestamp': fields.Datetime.now(),
        })
