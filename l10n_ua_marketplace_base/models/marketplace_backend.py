from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class MarketplaceBackend(models.Model):
    _name = 'marketplace.backend'
    _description = 'Marketplace Backend Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string='Code',
        readonly=True,
        copy=False,
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
    )
    marketplace_type = fields.Selection(
        selection='_selection_marketplace_type',
        string='Marketplace',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(
        default=True,
    )

    # === API Settings ===
    api_url = fields.Char(
        string='API URL',
        help='Base URL for marketplace API',
    )
    api_key = fields.Char(
        string='API Key',
        groups='base.group_system',
    )
    api_secret = fields.Char(
        string='API Secret',
        groups='base.group_system',
    )
    api_token = fields.Char(
        string='Current Token',
        groups='base.group_system',
        help='OAuth token or session token',
    )
    api_token_expiry = fields.Datetime(
        string='Token Expiry',
    )

    # === Feed Settings ===
    feed_enabled = fields.Boolean(
        string='Enable Feed',
        default=True,
    )
    feed_url = fields.Char(
        string='Feed URL',
        compute='_compute_feed_url',
    )
    feed_format = fields.Selection(
        selection=[
            ('yml', 'YML (Yandex Market)'),
            ('xml', 'XML'),
            ('csv', 'CSV'),
        ],
        string='Feed Format',
        default='yml',
    )
    feed_pricelist_id = fields.Many2one(
        'marketplace.pricelist',
        string='Feed Pricelist',
    )
    feed_auth_enabled = fields.Boolean(
        string='Feed Authentication',
        default=False,
    )
    feed_auth_login = fields.Char(
        string='Feed Login',
    )
    feed_auth_password = fields.Char(
        string='Feed Password',
    )

    # === Stock Sync ===
    sync_stock_enabled = fields.Boolean(
        string='Sync Stock',
        default=True,
    )
    sync_stock_interval = fields.Integer(
        string='Stock Sync Interval (min)',
        default=60,
    )
    sync_stock_last = fields.Datetime(
        string='Last Stock Sync',
        readonly=True,
    )
    sync_stock_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Stock Warehouse',
    )

    # === Price Sync ===
    sync_prices_enabled = fields.Boolean(
        string='Sync Prices',
        default=True,
    )
    sync_prices_interval = fields.Integer(
        string='Price Sync Interval (min)',
        default=60,
    )
    sync_prices_last = fields.Datetime(
        string='Last Price Sync',
        readonly=True,
    )

    # === Order Import ===
    import_orders_enabled = fields.Boolean(
        string='Import Orders',
        default=True,
    )
    import_orders_interval = fields.Integer(
        string='Order Import Interval (min)',
        default=15,
    )
    import_orders_last = fields.Datetime(
        string='Last Order Import',
        readonly=True,
    )
    import_orders_from_date = fields.Date(
        string='Import Orders From',
        help='Only import orders created after this date',
    )

    # === Webhook ===
    webhook_enabled = fields.Boolean(
        string='Enable Webhook',
        default=False,
    )
    webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_webhook_url',
    )
    webhook_secret = fields.Char(
        string='Webhook Secret',
        groups='base.group_system',
    )

    # === Partner Settings ===
    partner_creation_mode = fields.Selection(
        selection=[
            ('always', 'Always Create New'),
            ('if_not_found', 'Create If Not Found'),
            ('never', 'Never Create'),
        ],
        string='Partner Creation',
        default='if_not_found',
        required=True,
    )
    partner_search_by = fields.Selection(
        selection=[
            ('phone', 'By Phone'),
            ('email', 'By Email'),
            ('both', 'By Phone or Email'),
        ],
        string='Search Partner By',
        default='phone',
    )
    partner_default_category_id = fields.Many2one(
        'res.partner.category',
        string='Default Partner Category',
    )
    partner_assign_salesperson = fields.Boolean(
        string='Assign Salesperson',
        default=False,
    )
    partner_default_user_id = fields.Many2one(
        'res.users',
        string='Default Salesperson',
    )

    # === Warehouse & Delivery ===
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
    )
    delivery_carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Default Delivery Carrier',
    )

    # === Auto Create Sale Order ===
    auto_create_sale_order = fields.Boolean(
        string='Auto Create Sale Order',
        default=True,
        help='Automatically create sale.order when importing marketplace order',
    )
    auto_confirm_sale_order = fields.Boolean(
        string='Auto Confirm Sale Order',
        default=False,
    )
    sale_team_id = fields.Many2one(
        'crm.team',
        string='Sales Team',
    )

    # === Payment Settings ===
    payment_journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain="[('type', 'in', ['bank', 'cash'])]",
        help='Journal for auto-registering marketplace payments',
    )
    auto_register_payment = fields.Boolean(
        string='Auto-Register Payments',
        default=False,
        help='Automatically register payments when marketplace marks order as paid',
    )

    # === Batch Sync Settings ===
    sync_batch_size = fields.Integer(
        string='Batch Size',
        default=100,
        help='Number of products to sync in a single API call',
    )
    sync_error_handling = fields.Selection(
        selection=[
            ('continue', 'Continue with others'),
            ('retry', 'Retry failed items'),
            ('stop', 'Stop on first error'),
        ],
        string='Error Handling',
        default='continue',
        help='How to handle errors during batch sync',
    )

    # === Status Mappings ===
    status_mapping_ids = fields.One2many(
        'marketplace.status.mapping',
        'backend_id',
        string='Status Mappings',
    )
    status_mapping_count = fields.Integer(
        string='Status Mappings',
        compute='_compute_status_mapping_count',
    )

    # === Status ===
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('error', 'Error'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )
    last_error = fields.Text(
        string='Last Error',
        readonly=True,
    )
    last_error_date = fields.Datetime(
        string='Last Error Date',
        readonly=True,
    )

    # === Statistics ===
    order_count = fields.Integer(
        string='Orders',
        compute='_compute_order_count',
    )
    pricelist_item_count = fields.Integer(
        string='Products',
        compute='_compute_pricelist_item_count',
    )

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'Backend code must be unique!',
    )

    @api.model
    def _selection_marketplace_type(self):
        """Return available marketplace types. Override in child modules."""
        return [
            ('rozetka', 'Rozetka'),
            ('prom', 'Prom.ua'),
            ('epicentr', 'Epicentr'),
            ('allo', 'Allo'),
            ('hotline', 'Hotline'),
            ('priceua', 'Price.ua'),
        ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self.env['ir.sequence'].next_by_code('marketplace.backend') or 'NEW'
        return super().create(vals_list)

    def _compute_feed_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        for backend in self:
            if backend.id and backend.feed_enabled:
                backend.feed_url = f'{base_url}/marketplace/feed/{backend.id}'
            else:
                backend.feed_url = False

    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        for backend in self:
            if backend.id and backend.webhook_enabled:
                backend.webhook_url = f'{base_url}/marketplace/webhook/{backend.id}'
            else:
                backend.webhook_url = False

    def _compute_order_count(self):
        for backend in self:
            backend.order_count = self.env['marketplace.order'].search_count([
                ('backend_id', '=', backend.id)
            ])

    def _compute_pricelist_item_count(self):
        for backend in self:
            backend.pricelist_item_count = self.env['marketplace.pricelist.item'].search_count([
                ('backend_id', '=', backend.id)
            ])

    def _compute_status_mapping_count(self):
        for backend in self:
            backend.status_mapping_count = self.env['marketplace.status.mapping'].search_count([
                ('backend_id', '=', backend.id)
            ])

    # === Actions ===
    def action_activate(self):
        """Activate backend after testing connection."""
        self.ensure_one()
        self.action_test_connection()
        self.state = 'active'

    def action_test_connection(self):
        """Test API connection. Override in child modules."""
        self.ensure_one()
        # Base implementation - override in specific marketplace modules
        _logger.info(f"Testing connection for {self.name} ({self.marketplace_type})")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Connection Test'),
                'message': _('Connection test not implemented for this marketplace type.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_refresh_token(self):
        """Refresh API token. Override in child modules."""
        self.ensure_one()
        raise NotImplementedError(_('Token refresh not implemented for this marketplace type.'))

    def action_sync_stock_now(self):
        """Immediately sync stock levels."""
        self.ensure_one()
        self._sync_stock()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Stock Sync'),
                'message': _('Stock synchronization completed.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_prices_now(self):
        """Immediately sync prices."""
        self.ensure_one()
        self._sync_prices()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Price Sync'),
                'message': _('Price synchronization completed.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_import_orders_now(self):
        """Immediately import orders."""
        self.ensure_one()
        count = self._import_orders()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Order Import'),
                'message': _('%d orders imported.') % count,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_orders(self):
        """View orders from this backend."""
        self.ensure_one()
        return {
            'name': _('Marketplace Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.order',
            'view_mode': 'list,form',
            'domain': [('backend_id', '=', self.id)],
            'context': {'default_backend_id': self.id},
        }

    def action_view_pricelist_items(self):
        """View pricelist items for this backend."""
        self.ensure_one()
        return {
            'name': _('Marketplace Products'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.pricelist.item',
            'view_mode': 'list,form',
            'domain': [('backend_id', '=', self.id)],
            'context': {'default_backend_id': self.id},
        }

    # === Status Mapping Methods ===
    def _get_odoo_state(self, marketplace_code):
        """Map marketplace status code to Odoo state.

        Args:
            marketplace_code: Status code from marketplace API

        Returns:
            str: Odoo internal state ('new', 'confirmed', etc.) or 'new' if not found
        """
        self.ensure_one()
        mapping = self.env['marketplace.status.mapping'].search([
            ('backend_id', '=', self.id),
            ('external_code', '=', str(marketplace_code)),
            ('sync_from_marketplace', '=', True),
            ('active', '=', True),
        ], limit=1)
        return mapping.internal_state if mapping else 'new'

    def _get_marketplace_code(self, odoo_state):
        """Map Odoo state to marketplace status code.

        Args:
            odoo_state: Odoo internal state ('new', 'confirmed', etc.)

        Returns:
            str: Marketplace status code or None if not found
        """
        self.ensure_one()
        mapping = self.env['marketplace.status.mapping'].search([
            ('backend_id', '=', self.id),
            ('internal_state', '=', odoo_state),
            ('sync_to_marketplace', '=', True),
            ('active', '=', True),
        ], limit=1)
        return mapping.external_code if mapping else None

    def action_sync_statuses(self):
        """Sync available statuses from marketplace API. Override in child modules."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Status Sync'),
                'message': _('Status sync not implemented for this marketplace type.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_view_status_mappings(self):
        """View status mappings for this backend."""
        self.ensure_one()
        return {
            'name': _('Status Mappings'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.status.mapping',
            'view_mode': 'list,form',
            'domain': [('backend_id', '=', self.id)],
            'context': {'default_backend_id': self.id},
        }

    # === Sync Methods (with batch support) ===
    def _sync_stock(self):
        """Sync stock levels to marketplace using batch processing."""
        self.ensure_one()

        items = self.env['marketplace.pricelist.item'].search([
            ('backend_id', '=', self.id),
            ('state', 'in', ['published', 'pending']),
            ('active', '=', True),
            ('external_id', '!=', False),
        ])

        if not items:
            _logger.info(f"Stock sync for {self.name} - no items to sync")
            self.sync_stock_last = fields.Datetime.now()
            return

        # Process in batches
        batch_size = self.sync_batch_size or 100
        failed_items = self.env['marketplace.pricelist.item']

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            try:
                self._api_sync_stock_batch(batch)
            except Exception as e:
                _logger.error(f"Batch stock sync error for {self.name}: {e}")
                if self.sync_error_handling == 'stop':
                    raise
                elif self.sync_error_handling == 'retry':
                    failed_items |= batch
                # 'continue' - just log and continue

        # Retry failed items individually
        if failed_items and self.sync_error_handling == 'retry':
            for item in failed_items:
                try:
                    self._api_sync_stock_batch(item)
                except Exception as e:
                    _logger.error(f"Retry stock sync failed for item {item.id}: {e}")
                    item.write({'sync_error': str(e)})

        self.sync_stock_last = fields.Datetime.now()

    def _sync_prices(self):
        """Sync prices to marketplace using batch processing."""
        self.ensure_one()

        items = self.env['marketplace.pricelist.item'].search([
            ('backend_id', '=', self.id),
            ('state', 'in', ['published', 'pending']),
            ('active', '=', True),
            ('external_id', '!=', False),
        ])

        if not items:
            _logger.info(f"Price sync for {self.name} - no items to sync")
            self.sync_prices_last = fields.Datetime.now()
            return

        # Process in batches
        batch_size = self.sync_batch_size or 100
        failed_items = self.env['marketplace.pricelist.item']

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            try:
                self._api_sync_prices_batch(batch)
            except Exception as e:
                _logger.error(f"Batch price sync error for {self.name}: {e}")
                if self.sync_error_handling == 'stop':
                    raise
                elif self.sync_error_handling == 'retry':
                    failed_items |= batch

        # Retry failed items individually
        if failed_items and self.sync_error_handling == 'retry':
            for item in failed_items:
                try:
                    self._api_sync_prices_batch(item)
                except Exception as e:
                    _logger.error(f"Retry price sync failed for item {item.id}: {e}")
                    item.write({'sync_error': str(e)})

        self.sync_prices_last = fields.Datetime.now()

    def _import_orders(self):
        """Import orders from marketplace. Override in child modules."""
        self.ensure_one()
        _logger.info(f"Order import for {self.name} - not implemented")
        self.import_orders_last = fields.Datetime.now()
        return 0

    def _generate_feed(self):
        """Generate product feed. Override in child modules."""
        self.ensure_one()
        if not self.feed_pricelist_id:
            raise UserError(_('Please configure a pricelist for the feed.'))
        return self.feed_pricelist_id._generate_feed(self.feed_format)

    # === API Methods (to override) ===
    def _api_authenticate(self):
        """Authenticate with marketplace API. Override in child modules."""
        raise NotImplementedError()

    def _api_get_orders(self, from_date=None):
        """Get orders from API. Override in child modules."""
        raise NotImplementedError()

    def _api_update_order_status(self, order, status, tracking=None):
        """Update order status via API. Override in child modules."""
        raise NotImplementedError()

    def _api_cancel_order(self, order, reason=None, comment=None):
        """Cancel order on marketplace. Override in child modules.

        Args:
            order: marketplace.order record
            reason: Cancel reason code
            comment: Optional comment text
        """
        _logger.info(f"Cancel order {order.name} on {self.name} - not implemented")

    def _api_sync_stock(self, items):
        """Sync stock via API (single item). Override in child modules."""
        raise NotImplementedError()

    def _api_sync_prices(self, items):
        """Sync prices via API (single item). Override in child modules."""
        raise NotImplementedError()

    def _api_sync_stock_batch(self, items):
        """Sync stock via API (batch). Override in child modules for batch support.

        Default implementation: calls individual sync for each item.
        """
        for item in items:
            try:
                self._api_sync_stock(item)
                item.write({
                    'last_sync': fields.Datetime.now(),
                    'sync_error': False,
                })
            except Exception as e:
                _logger.error(f"Stock sync error for item {item.id}: {e}")
                item.write({'sync_error': str(e)})
                if self.sync_error_handling == 'stop':
                    raise

    def _api_sync_prices_batch(self, items):
        """Sync prices via API (batch). Override in child modules for batch support.

        Default implementation: calls individual sync for each item.
        """
        for item in items:
            try:
                self._api_sync_prices(item)
                item.write({
                    'last_sync': fields.Datetime.now(),
                    'sync_error': False,
                })
            except Exception as e:
                _logger.error(f"Price sync error for item {item.id}: {e}")
                item.write({'sync_error': str(e)})
                if self.sync_error_handling == 'stop':
                    raise

    # === Cron Methods ===
    @api.model
    def _cron_import_orders_all(self):
        """Cron: Import orders from all active backends."""
        backends = self.search([
            ('state', '=', 'active'),
            ('import_orders_enabled', '=', True),
        ])
        for backend in backends:
            try:
                backend._import_orders()
            except Exception as e:
                _logger.exception(f"Error importing orders for {backend.name}: {e}")
                backend.write({
                    'last_error': str(e),
                    'last_error_date': fields.Datetime.now(),
                    'state': 'error',
                })

    @api.model
    def _cron_sync_stock_all(self):
        """Cron: Sync stock for all active backends."""
        backends = self.search([
            ('state', '=', 'active'),
            ('sync_stock_enabled', '=', True),
        ])
        for backend in backends:
            try:
                backend._sync_stock()
            except Exception as e:
                _logger.exception(f"Error syncing stock for {backend.name}: {e}")
                backend.write({
                    'last_error': str(e),
                    'last_error_date': fields.Datetime.now(),
                })

    @api.model
    def _cron_sync_prices_all(self):
        """Cron: Sync prices for all active backends."""
        backends = self.search([
            ('state', '=', 'active'),
            ('sync_prices_enabled', '=', True),
        ])
        for backend in backends:
            try:
                backend._sync_prices()
            except Exception as e:
                _logger.exception(f"Error syncing prices for {backend.name}: {e}")
                backend.write({
                    'last_error': str(e),
                    'last_error_date': fields.Datetime.now(),
                })

    @api.model
    def _cron_refresh_tokens(self):
        """Cron: Refresh API tokens before expiry."""
        backends = self.search([
            ('state', '=', 'active'),
            ('api_token_expiry', '!=', False),
            ('api_token_expiry', '<=', fields.Datetime.add(fields.Datetime.now(), hours=2)),
        ])
        for backend in backends:
            try:
                backend.action_refresh_token()
            except Exception as e:
                _logger.exception(f"Error refreshing token for {backend.name}: {e}")

    # === Error Handling ===
    def _set_error(self, error_message):
        """Set backend to error state with message."""
        self.ensure_one()
        self.write({
            'state': 'error',
            'last_error': error_message,
            'last_error_date': fields.Datetime.now(),
        })

    def _clear_error(self):
        """Clear error state."""
        self.ensure_one()
        if self.state == 'error':
            self.write({
                'state': 'active',
                'last_error': False,
                'last_error_date': False,
            })
