import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class MarketplaceBackendHotline(models.Model):
    """Hotline.ua marketplace backend extension.

    Hotline.ua is a price comparison portal that works via YML feed only.
    No API integration for orders or stock synchronization.
    """

    _inherit = 'marketplace.backend'

    # Hotline-specific fields
    hotline_merchant_id = fields.Char(
        string='Hotline Merchant ID',
        help='Your merchant ID in Hotline system (for reference)',
    )
    hotline_feed_category_id = fields.Many2one(
        'marketplace.category',
        string='Hotline Root Category',
        domain="[('marketplace_type', '=', 'hotline')]",
        help='Root category for Hotline feed (optional)',
    )

    # Note: 'hotline' marketplace_type is already defined in l10n_ua_marketplace_base

    def _get_hotline_feed_url(self):
        """Get the feed URL for Hotline submission."""
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
                'message': self._get_hotline_feed_url(),
                'type': 'info',
                'sticky': True,
            },
        }
