from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class MarketplaceOrder(models.Model):
    _name = 'marketplace.order'
    _description = 'Marketplace Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'order_date desc, id desc'

    name = fields.Char(
        string='Order Reference',
        required=True,
        index=True,
    )
    backend_id = fields.Many2one(
        'marketplace.backend',
        string='Backend',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    marketplace_type = fields.Selection(
        related='backend_id.marketplace_type',
        string='Marketplace Type',
        store=True,
    )
    external_id = fields.Char(
        string='External Order ID',
        required=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='backend_id.company_id',
        store=True,
    )

    # === Odoo Links ===
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        tracking=True,
    )
    picking_ids = fields.One2many(
        'stock.picking',
        compute='_compute_picking_ids',
    )
    picking_count = fields.Integer(
        compute='_compute_picking_ids',
    )
    invoice_ids = fields.One2many(
        'account.move',
        compute='_compute_invoice_ids',
    )
    invoice_count = fields.Integer(
        compute='_compute_invoice_ids',
    )

    # === Dates ===
    order_date = fields.Datetime(
        string='Order Date',
        tracking=True,
    )
    import_date = fields.Datetime(
        string='Import Date',
        default=fields.Datetime.now,
    )
    confirm_date = fields.Datetime(
        string='Confirm Date',
    )
    ship_date = fields.Datetime(
        string='Ship Date',
    )

    # === Status ===
    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('processing', 'Processing'),
            ('confirmed', 'Confirmed'),
            ('shipped', 'Shipped'),
            ('delivered', 'Delivered'),
            ('cancelled', 'Cancelled'),
            ('returned', 'Returned'),
        ],
        string='State',
        default='new',
        tracking=True,
        index=True,
    )
    marketplace_state = fields.Char(
        string='Marketplace State',
        help='Original state from marketplace',
    )
    marketplace_state_code = fields.Char(
        string='Marketplace State Code',
    )

    # === Financials ===
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    amount_untaxed = fields.Monetary(
        string='Untaxed Amount',
        currency_field='currency_id',
    )
    amount_tax = fields.Monetary(
        string='Taxes',
        currency_field='currency_id',
    )
    amount_total = fields.Monetary(
        string='Total',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
    )
    amount_delivery = fields.Monetary(
        string='Delivery Amount',
        currency_field='currency_id',
    )
    commission_amount = fields.Monetary(
        string='Commission',
        currency_field='currency_id',
        help='Marketplace commission',
    )
    payment_method = fields.Char(
        string='Payment Method',
    )
    is_paid = fields.Boolean(
        string='Paid',
        default=False,
    )
    payment_status_id = fields.Many2one(
        'marketplace.payment.status',
        string='Payment Status',
    )
    payment_date = fields.Datetime(
        string='Payment Date',
    )
    payment_amount = fields.Monetary(
        string='Payment Amount',
        currency_field='currency_id',
    )
    payment_id = fields.Many2one(
        'account.payment',
        string='Registered Payment',
    )

    # === Cancellation ===
    cancel_reason = fields.Selection(
        selection=[
            ('customer_request', 'Customer Request'),
            ('out_of_stock', 'Out of Stock'),
            ('pricing_error', 'Pricing Error'),
            ('duplicate_order', 'Duplicate Order'),
            ('fraud_suspicion', 'Fraud Suspicion'),
            ('delivery_issue', 'Delivery Issue'),
            ('other', 'Other'),
        ],
        string='Cancel Reason',
    )
    cancel_comment = fields.Text(
        string='Cancel Comment',
    )

    # === Customer Info ===
    customer_name = fields.Char(
        string='Customer Name',
    )
    customer_phone = fields.Char(
        string='Customer Phone',
    )
    customer_email = fields.Char(
        string='Customer Email',
    )
    customer_comment = fields.Text(
        string='Customer Comment',
    )

    # === Delivery ===
    delivery_method = fields.Char(
        string='Delivery Method',
    )
    delivery_carrier_name = fields.Char(
        string='Carrier Name',
    )
    delivery_address = fields.Text(
        string='Delivery Address',
    )
    delivery_city = fields.Char(
        string='City',
    )
    delivery_region = fields.Char(
        string='Region',
    )
    delivery_warehouse = fields.Char(
        string='Warehouse/Post Office',
    )
    delivery_zip = fields.Char(
        string='ZIP Code',
    )
    tracking_number = fields.Char(
        string='Tracking Number (TTN)',
        tracking=True,
    )

    # === Lines ===
    line_ids = fields.One2many(
        'marketplace.order.line',
        'order_id',
        string='Order Lines',
    )
    line_count = fields.Integer(
        compute='_compute_line_count',
    )

    # === Raw Data ===
    raw_data = fields.Text(
        string='Raw Data',
        help='Original JSON data from marketplace',
    )

    _external_backend_uniq = models.Constraint(
        'UNIQUE(external_id, backend_id)',
        'External order ID must be unique per backend!',
    )

    @api.depends('line_ids.price_total', 'amount_delivery')
    def _compute_amounts(self):
        for order in self:
            order.amount_total = sum(order.line_ids.mapped('price_total')) + (order.amount_delivery or 0)

    def _compute_line_count(self):
        for order in self:
            order.line_count = len(order.line_ids)

    def _compute_picking_ids(self):
        for order in self:
            if order.sale_order_id:
                order.picking_ids = order.sale_order_id.picking_ids
                order.picking_count = len(order.picking_ids)
            else:
                order.picking_ids = False
                order.picking_count = 0

    def _compute_invoice_ids(self):
        for order in self:
            if order.sale_order_id:
                order.invoice_ids = order.sale_order_id.invoice_ids
                order.invoice_count = len(order.invoice_ids)
            else:
                order.invoice_ids = False
                order.invoice_count = 0

    # === Actions ===
    def action_create_sale_order(self):
        """Create sale.order from marketplace order."""
        self.ensure_one()

        if self.sale_order_id:
            raise UserError(_('Sale order already exists for this marketplace order.'))

        if not self.partner_id:
            self._find_or_create_partner()

        if not self.partner_id:
            raise UserError(_('Cannot create sale order without a customer.'))

        # Prepare order values
        so_vals = self._prepare_sale_order_vals()

        # Create sale order
        sale_order = self.env['sale.order'].create(so_vals)

        # Create order lines
        for line in self.line_ids:
            line_vals = line._prepare_sale_order_line_vals(sale_order)
            self.env['sale.order.line'].create(line_vals)

        self.sale_order_id = sale_order

        # Auto confirm if configured
        if self.backend_id.auto_confirm_sale_order:
            sale_order.action_confirm()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
        }

    def _prepare_sale_order_vals(self):
        """Prepare values for sale.order creation."""
        self.ensure_one()

        vals = {
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'date_order': self.order_date or fields.Datetime.now(),
            'client_order_ref': f"{self.backend_id.marketplace_type.upper()}: {self.name}",
            'origin': self.name,
        }

        if self.backend_id.warehouse_id:
            vals['warehouse_id'] = self.backend_id.warehouse_id.id

        if self.backend_id.sale_team_id:
            vals['team_id'] = self.backend_id.sale_team_id.id

        if self.backend_id.partner_default_user_id:
            vals['user_id'] = self.backend_id.partner_default_user_id.id

        return vals

    def _find_or_create_partner(self):
        """Find existing partner or create new one based on backend settings."""
        self.ensure_one()
        backend = self.backend_id

        # Never create mode
        if backend.partner_creation_mode == 'never':
            return

        partner = False
        Partner = self.env['res.partner']

        # Search for existing partner
        if backend.partner_creation_mode == 'if_not_found':
            domain = []

            if backend.partner_search_by in ('phone', 'both') and self.customer_phone:
                phone = self._normalize_phone(self.customer_phone)
                # phone_mobile_search looks through all partner phone fields,
                # ignoring how the number is formatted in the database
                if len(phone) >= 3:
                    domain = [('phone_mobile_search', 'ilike', phone)]

            if backend.partner_search_by in ('email', 'both') and self.customer_email:
                email_domain = [('email', '=ilike', self.customer_email)]
                if domain:
                    domain = ['|'] + domain + email_domain
                else:
                    domain = email_domain

            if domain:
                partner = Partner.search(domain, limit=1)

        # Create new partner if not found or always create
        if not partner and backend.partner_creation_mode in ('always', 'if_not_found'):
            partner_vals = self._prepare_partner_vals()
            partner = Partner.create(partner_vals)

        self.partner_id = partner

    def _prepare_partner_vals(self):
        """Prepare values for res.partner creation."""
        self.ensure_one()
        backend = self.backend_id

        vals = {
            'name': self.customer_name or self.customer_phone or 'Unknown',
            'phone': self.customer_phone,
            'email': self.customer_email,
            'is_marketplace_customer': True,
            'marketplace_source': self.marketplace_type,
            'company_id': self.company_id.id,
        }

        # Address
        if self.delivery_address or self.delivery_city:
            vals.update({
                'street': self.delivery_address,
                'city': self.delivery_city,
                'zip': self.delivery_zip,
            })

        # Category
        if backend.partner_default_category_id:
            vals['category_id'] = [(4, backend.partner_default_category_id.id)]

        # Salesperson
        if backend.partner_assign_salesperson and backend.partner_default_user_id:
            vals['user_id'] = backend.partner_default_user_id.id

        return vals

    @staticmethod
    def _normalize_phone(phone):
        """Normalize phone number for search."""
        if not phone:
            return ''
        # Remove all non-digits except +
        import re
        normalized = re.sub(r'[^\d+]', '', phone)
        # Take last 10 digits for Ukrainian phones
        if len(normalized) >= 10:
            normalized = normalized[-10:]
        return normalized

    def action_confirm(self):
        """Confirm order and update status on marketplace."""
        self.ensure_one()
        self.write({
            'state': 'confirmed',
            'confirm_date': fields.Datetime.now(),
        })
        # Sync status to marketplace
        try:
            self.backend_id._api_update_order_status(self, 'confirmed')
        except NotImplementedError:
            pass  # API not implemented for this marketplace

    def action_ship(self):
        """Ship order (wizard for TTN entry)."""
        self.ensure_one()
        return {
            'name': _('Ship Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.order.ship.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_mark_shipped(self, tracking_number=None):
        """Mark order as shipped with optional tracking number."""
        self.ensure_one()
        vals = {
            'state': 'shipped',
            'ship_date': fields.Datetime.now(),
        }
        if tracking_number:
            vals['tracking_number'] = tracking_number

        self.write(vals)

        # Sync status to marketplace
        try:
            self.backend_id._api_update_order_status(self, 'shipped', tracking_number)
        except NotImplementedError:
            pass

    def action_deliver(self):
        """Mark order as delivered."""
        self.ensure_one()
        self.state = 'delivered'
        try:
            self.backend_id._api_update_order_status(self, 'delivered')
        except NotImplementedError:
            pass

    def action_cancel(self):
        """Open cancel wizard instead of direct cancel."""
        return {
            'name': _('Cancel Marketplace Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.order.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_ids': [(6, 0, self.ids)],
            },
        }

    def action_cancel_direct(self, reason=None, comment=None, sync_to_marketplace=True):
        """Direct cancel without wizard (for programmatic use)."""
        for order in self:
            vals = {'state': 'cancelled'}
            if reason:
                vals['cancel_reason'] = reason
            if comment:
                vals['cancel_comment'] = comment
            order.write(vals)

            # Sync to marketplace if requested
            if sync_to_marketplace:
                try:
                    order.backend_id._api_cancel_order(order, reason=reason, comment=comment)
                except Exception as e:
                    _logger.warning("Failed to sync cancel to marketplace for order %s: %s", order.name, e)

            # Cancel linked sale order if exists and not already done/cancelled
            if order.sale_order_id and order.sale_order_id.state not in ('done', 'cancel'):
                order.sale_order_id._action_cancel()

            # Post to chatter
            order.message_post(
                body=_("Order cancelled. Reason: %s. %s") % (
                    dict(order._fields['cancel_reason'].selection).get(reason, reason or 'Not specified'),
                    comment or ''
                )
            )

    def _register_payment(self, amount=None, payment_date=None):
        """Register payment for this order.

        This method:
        1. Confirms the sale order if draft
        2. Creates invoice if needed
        3. Posts draft invoices
        4. Registers payment via account.payment.register wizard

        Args:
            amount: Payment amount. If not specified, uses order total.
            payment_date: Payment date. If not specified, uses today.

        Returns:
            account.payment record or False if failed
        """
        self.ensure_one()

        if not self.sale_order_id:
            _logger.warning("Cannot register payment for order %s: no linked sale order", self.name)
            return False

        if not self.backend_id.payment_journal_id:
            _logger.warning("Cannot register payment for order %s: no payment journal configured", self.name)
            return False

        sale_order = self.sale_order_id

        # 1. Confirm SO if draft
        if sale_order.state == 'draft':
            sale_order.action_confirm()

        # 2. Create invoice if needed
        if not sale_order.invoice_ids:
            try:
                sale_order._create_invoices()
            except Exception as e:
                _logger.error("Failed to create invoice for order %s: %s", self.name, e)
                return False

        # 3. Post draft invoices
        for invoice in sale_order.invoice_ids.filtered(lambda i: i.state == 'draft'):
            try:
                invoice.action_post()
            except Exception as e:
                _logger.error("Failed to post invoice %s: %s", invoice.name, e)
                return False

        # 4. Register payment for open invoices
        open_invoices = sale_order.invoice_ids.filtered(
            lambda i: i.state == 'posted' and i.payment_state not in ('paid', 'in_payment')
        )

        if not open_invoices:
            _logger.info("No open invoices to pay for order %s", self.name)
            return False

        payment_amount = amount or self.amount_total
        pay_date = payment_date or fields.Date.today()

        try:
            ctx = {
                'active_model': 'account.move',
                'active_ids': open_invoices.ids,
            }
            wizard = self.env['account.payment.register'].with_context(**ctx).create({
                'amount': payment_amount,
                'payment_date': pay_date,
                'journal_id': self.backend_id.payment_journal_id.id,
            })
            payment = wizard._create_payments()

            # Update marketplace order with payment info
            self.write({
                'payment_id': payment.id if len(payment) == 1 else payment[0].id,
                'payment_date': fields.Datetime.now(),
                'payment_amount': payment_amount,
                'is_paid': True,
            })

            self.message_post(
                body=_("Payment of %s %s registered automatically from marketplace.") % (
                    payment_amount, self.currency_id.symbol or ''
                )
            )

            return payment

        except Exception as e:
            _logger.error("Failed to register payment for order %s: %s", self.name, e)
            return False

    def action_register_payment(self):
        """Manually register payment for this order."""
        self.ensure_one()

        if self.is_paid:
            raise UserError(_('This order is already marked as paid.'))

        if not self.sale_order_id:
            raise UserError(_('Cannot register payment: no sale order linked. Create a sale order first.'))

        if not self.backend_id.payment_journal_id:
            raise UserError(_('Cannot register payment: no payment journal configured on backend.'))

        payment = self._register_payment()
        if payment:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.payment',
                'res_id': payment[:1].id,
                'view_mode': 'form',
            }
        else:
            raise UserError(_('Failed to register payment. Check the logs for details.'))

    def action_sync_status(self):
        """Sync status from marketplace."""
        self.ensure_one()
        # To be implemented in specific marketplace modules
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Status'),
                'message': _('Status sync not implemented for this marketplace.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_view_sale_order(self):
        """View linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('No sale order linked.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
        }

    def action_view_pickings(self):
        """View linked pickings."""
        self.ensure_one()
        return {
            'name': _('Deliveries'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
        }

    def action_view_invoices(self):
        """View linked invoices."""
        self.ensure_one()
        return {
            'name': _('Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }

    @api.model
    def create_from_api_data(self, backend, data):
        """Create order from API response data. Override in specific modules."""
        raise NotImplementedError()


class MarketplaceOrderLine(models.Model):
    _name = 'marketplace.order.line'
    _description = 'Marketplace Order Line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'marketplace.order',
        string='Order',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        default=10,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
    )
    external_product_id = fields.Char(
        string='External Product ID',
    )
    name = fields.Char(
        string='Description',
        required=True,
    )
    sku = fields.Char(
        string='SKU',
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
    )
    price_unit = fields.Float(
        string='Unit Price',
    )
    discount = fields.Float(
        string='Discount %',
    )
    price_total = fields.Float(
        string='Total',
        compute='_compute_price_total',
        store=True,
    )
    currency_id = fields.Many2one(
        related='order_id.currency_id',
    )

    @api.depends('quantity', 'price_unit', 'discount')
    def _compute_price_total(self):
        for line in self:
            price = line.price_unit * (1 - line.discount / 100.0)
            line.price_total = price * line.quantity

    def _find_product(self):
        """Find product by SKU or external ID."""
        self.ensure_one()
        Product = self.env['product.product']

        # Search by SKU
        if self.sku:
            product = Product.search([('default_code', '=', self.sku)], limit=1)
            if product:
                return product

        # Search by barcode
        if self.external_product_id:
            product = Product.search([('barcode', '=', self.external_product_id)], limit=1)
            if product:
                return product

        return False

    def _prepare_sale_order_line_vals(self, sale_order):
        """Prepare values for sale.order.line creation."""
        self.ensure_one()

        product = self.product_id or self._find_product()

        vals = {
            'order_id': sale_order.id,
            'name': self.name,
            'product_uom_qty': self.quantity,
            'price_unit': self.price_unit,
        }

        if product:
            vals['product_id'] = product.id
            if product.uom_id:
                vals['product_uom_id'] = product.uom_id.id

        if self.discount:
            vals['discount'] = self.discount

        return vals
