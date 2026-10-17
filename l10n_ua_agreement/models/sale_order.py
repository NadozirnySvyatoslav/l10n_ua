from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        ondelete='restrict',
        tracking=True,
        copy=False,
        index='btree_not_null',
        domain="[('commercial_partner_id', '=', l10n_ua_commercial_partner_id),"
               " ('direction', '=', 'sale'), ('state', 'in', ('to_sign', 'signed')),"
               " ('company_id', '=', company_id)]",
    )
    l10n_ua_commercial_partner_id = fields.Many2one(
        related='partner_id.commercial_partner_id', string='Commercial Partner')
