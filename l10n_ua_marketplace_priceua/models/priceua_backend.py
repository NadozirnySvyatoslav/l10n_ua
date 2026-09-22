import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class MarketplaceBackendPriceUA(models.Model):
    """Price.ua marketplace backend extension.

    Price.ua is a price comparison portal that works via YML feed only.
    No API integration for orders or stock synchronization.
    """

    _inherit = 'marketplace.backend'

    # Price.ua-specific fields
    priceua_merchant_id = fields.Char(
        string='Price.ua Merchant ID',
        help='Your merchant ID in Price.ua system (for reference)',
    )
    priceua_feed_category_id = fields.Many2one(
        'marketplace.category',
        string='Price.ua Root Category',
        domain="[('marketplace_type', '=', 'priceua')]",
        help='Root category for Price.ua feed (optional)',
    )

    # Note: 'priceua' marketplace_type is already defined in l10n_ua_marketplace_base

    def _get_priceua_feed_url(self):
        """Get the feed URL for Price.ua submission."""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        return f'{base_url}/marketplace/feed/{self.id}'

    def action_copy_feed_url(self):
        """Copy feed URL to clipboard (via client action)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Feed URL',
                'message': self._get_priceua_feed_url(),
                'type': 'info',
                'sticky': True,
            },
        }
