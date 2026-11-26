from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        ondelete='restrict',
        tracking=True,
        index=True,
        copy=False,
        help='The agreement this document is settled under. Taken over from '
             'the sales order.',
    )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        related='move_id.l10n_ua_agreement_id',
        store=True,
        index=True,
        help='The agreement of the journal entry, for the 361/631 trial balance '
             'and settlements by agreement.',
    )
