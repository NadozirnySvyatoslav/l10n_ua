from odoo import api, models
from odoo.tools.mail import decode_message_header, email_normalize_all


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_route(self, message, message_dict, model=None, thread_id=None, custom_values=None):
        """A message written to the EDO alias is not also a message to the mailbox it came through.

        A hosting alias (edo@ → info@) delivers into the info@ mailbox and adds
        ``Delivered-To: info@``; Odoo then routes the message to both aliases and
        an incoming document also becomes a CRM lead. When the EDO alias is among
        the routes, other alias routes stay only if their address is in To / Cc.
        """
        routes = super().message_route(message, message_dict, model=model, thread_id=thread_id,
                                       custom_values=custom_values)
        edo = [r for r in routes if r[0] == 'l10n_ua.edo.document' and r[4]]
        if not edo or len(edo) == len(routes):
            return routes
        # message_dict['to'] already has Delivered-To merged in: read the headers
        visible = set(email_normalize_all(','.join(filter(None, (
            decode_message_header(message, 'To', separator=','),
            decode_message_header(message, 'Cc', separator=','))))))
        return [r for r in routes
                if not r[4] or r in edo or (r[4].alias_full_name or '').lower() in visible]
