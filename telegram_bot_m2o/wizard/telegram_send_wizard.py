import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


class TelegramSendWizard(models.TransientModel):
    _name = 'telegram.send.wizard'
    _description = 'Send Telegram Message'

    partner_id = fields.Many2one('res.partner', string='Contact', required=True)
    chat_id = fields.Many2one(
        'telegram.bot.chat', string='Telegram Chat', required=True,
        domain="[('partner_id', '=', partner_id)]",
    )
    recipient_label = fields.Char(string='To', compute='_compute_recipient_label')
    message_text = fields.Text(string='Message')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'telegram_send_wizard_attachment_rel',
        'wizard_id', 'attachment_id', string='Photos / Files',
    )

    @api.depends('chat_id')
    def _compute_recipient_label(self):
        for wiz in self:
            chat = wiz.chat_id
            if chat:
                name = ('@' + chat.user_name) if chat.user_name else (chat.telegram_chat_id or '')
                wiz.recipient_label = '%s · @%s' % (name, chat.bot_id.username or 'bot')
            else:
                wiz.recipient_label = ''

    def action_send(self):
        self.ensure_one()
        chat = self.chat_id
        if not chat:
            raise UserError(_("No Telegram chat selected."))
        if chat.state == 'blocked':
            raise UserError(_("This user has blocked the bot — the message cannot be delivered."))
        if not chat.bot_id:
            raise UserError(_("This chat has no bot configured."))

        text = (self.message_text or '').strip()
        attachments = self.attachment_ids
        if not text and not attachments:
            raise UserError(_("Type a message or attach a photo/file."))

        # The bot is a system actor (like the webhook), so any internal user with
        # the button may send without telegram.bot.* rights.
        bot = chat.bot_id.sudo()
        cid = chat.telegram_chat_id

        def _check(result, what):
            if not result:
                raise UserError(_("Failed to send %s. See the bot log for details.") % what)

        if attachments:
            # Use the text as caption on the first attachment when it fits;
            # otherwise send it as a separate message first.
            caption = text if (text and len(text) <= CAPTION_LIMIT) else None
            if text and caption is None:
                _check(bot.send_message(cid, text, parse_mode=None), _("the message"))
            first = True
            for att in attachments:
                cap = caption if first else None
                if (att.mimetype or '').startswith('image/'):
                    _check(
                        bot.send_photo(cid, att.datas, caption=cap,
                                       filename=att.name or 'image', parse_mode=None),
                        att.name or _("photo"),
                    )
                else:
                    _check(
                        bot.send_document(cid, att.datas, att.name or 'file',
                                          caption=cap, parse_mode=None),
                        att.name or _("file"),
                    )
                first = False
        else:
            _check(bot.send_message(cid, text, parse_mode=None), _("the message"))

        return {'type': 'ir.actions.act_window_close'}
