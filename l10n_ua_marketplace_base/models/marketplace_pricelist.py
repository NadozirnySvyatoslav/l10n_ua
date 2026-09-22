from odoo import api, fields, models, _
from odoo.exceptions import UserError
from lxml import etree
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class MarketplacePricelist(models.Model):
    _name = 'marketplace.pricelist'
    _description = 'Marketplace Pricelist'
    _order = 'name'

    name = fields.Char(
        string='Name',
        required=True,
    )
    backend_id = fields.Many2one(
        'marketplace.backend',
        string='Marketplace Backend',
        required=True,
        ondelete='cascade',
    )
    marketplace_type = fields.Selection(
        related='backend_id.marketplace_type',
        store=True,
    )
    company_id = fields.Many2one(
        related='backend_id.company_id',
        store=True,
    )
    active = fields.Boolean(
        default=True,
    )

    # === Pricing ===
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Odoo Pricelist',
        help='Use prices from this Odoo pricelist',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    price_margin = fields.Float(
        string='Price Margin %',
        default=0,
        help='Additional margin to apply on prices',
    )
    price_round = fields.Float(
        string='Price Rounding',
        default=1.0,
        help='Round prices to this precision (e.g., 1.0 for whole numbers)',
    )
    min_price = fields.Float(
        string='Minimum Price',
        help='Minimum price for products',
    )

    # === Product Filters ===
    product_domain = fields.Char(
        string='Product Filter',
        default='[]',
        help='Odoo domain to filter products',
    )
    category_ids = fields.Many2many(
        'product.category',
        string='Product Categories',
        help='Only include products from these categories',
    )
    include_out_of_stock = fields.Boolean(
        string='Include Out of Stock',
        default=False,
    )
    min_qty_available = fields.Float(
        string='Minimum Quantity',
        default=1,
        help='Minimum available quantity to include product',
    )
    exclude_no_image = fields.Boolean(
        string='Exclude Without Image',
        default=True,
    )

    # === Items ===
    item_ids = fields.One2many(
        'marketplace.pricelist.item',
        'pricelist_id',
        string='Items',
    )
    item_count = fields.Integer(
        string='Item Count',
        compute='_compute_item_count',
    )

    # === Feed ===
    last_generation = fields.Datetime(
        string='Last Feed Generation',
        readonly=True,
    )

    def _compute_item_count(self):
        for pricelist in self:
            pricelist.item_count = len(pricelist.item_ids)

    def action_generate_items(self):
        """Generate pricelist items from products matching filter."""
        self.ensure_one()

        # Build domain
        domain = [
            ('sale_ok', '=', True),
            ('active', '=', True),
        ]

        # Add category filter
        if self.category_ids:
            domain.append(('categ_id', 'child_of', self.category_ids.ids))

        # Add custom domain
        if self.product_domain and self.product_domain != '[]':
            try:
                import ast
                custom_domain = ast.literal_eval(self.product_domain)
                domain.extend(custom_domain)
            except Exception as e:
                raise UserError(_('Invalid product filter domain: %s') % e)

        products = self.env['product.template'].search(domain)

        # Filter by image
        if self.exclude_no_image:
            products = products.filtered(lambda p: p.image_1920)

        # Get existing items
        existing_product_ids = self.item_ids.mapped('product_tmpl_id').ids

        # Create new items
        items_to_create = []
        for product in products:
            if product.id not in existing_product_ids:
                items_to_create.append({
                    'pricelist_id': self.id,
                    'product_tmpl_id': product.id,
                    'state': 'draft',
                })

        if items_to_create:
            self.env['marketplace.pricelist.item'].create(items_to_create)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Items Generated'),
                'message': _('%d new items added.') % len(items_to_create),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_refresh_prices(self):
        """Refresh prices for all items."""
        self.ensure_one()
        for item in self.item_ids:
            item._compute_price()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Prices Refreshed'),
                'message': _('Prices updated for %d items.') % len(self.item_ids),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_items(self):
        """View pricelist items."""
        self.ensure_one()
        return {
            'name': _('Pricelist Items'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.pricelist.item',
            'view_mode': 'list,form',
            'domain': [('pricelist_id', '=', self.id)],
            'context': {'default_pricelist_id': self.id},
        }

    def _generate_feed(self, feed_format='yml'):
        """Generate product feed."""
        self.ensure_one()

        if feed_format == 'yml':
            return self._generate_yml_feed()
        elif feed_format == 'xml':
            return self._generate_xml_feed()
        else:
            raise UserError(_('Unknown feed format: %s') % feed_format)

    def _generate_yml_feed(self):
        """Generate YML (Yandex Market Language) feed."""
        self.ensure_one()

        root = etree.Element('yml_catalog', date=datetime.now().strftime('%Y-%m-%d %H:%M'))
        shop = etree.SubElement(root, 'shop')

        # Shop info
        company = self.company_id
        etree.SubElement(shop, 'name').text = company.name
        etree.SubElement(shop, 'company').text = company.name
        if company.website:
            etree.SubElement(shop, 'url').text = company.website

        # Currencies
        currencies = etree.SubElement(shop, 'currencies')
        currency = etree.SubElement(currencies, 'currency', id=self.currency_id.name, rate='1')

        # Categories
        categories = etree.SubElement(shop, 'categories')
        category_ids = set()
        for item in self.item_ids.filtered(lambda i: i.state == 'published'):
            if item.marketplace_category_id:
                cat = item.marketplace_category_id
                while cat:
                    category_ids.add(cat.id)
                    cat = cat.parent_id

        for cat in self.env['marketplace.category'].browse(list(category_ids)):
            attrs = {'id': str(cat.external_id or cat.id)}
            if cat.parent_id:
                attrs['parentId'] = str(cat.parent_id.external_id or cat.parent_id.id)
            etree.SubElement(categories, 'category', **attrs).text = cat.name

        # Offers
        offers = etree.SubElement(shop, 'offers')
        for item in self.item_ids.filtered(lambda i: i.state == 'published' and i.active):
            self._add_yml_offer(offers, item)

        self.last_generation = fields.Datetime.now()

        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='UTF-8')

    def _add_yml_offer(self, offers_element, item):
        """Add single offer to YML feed."""
        product = item.product_tmpl_id

        # Check stock
        if not self.include_out_of_stock and item.qty_available < self.min_qty_available:
            return

        available = 'true' if item.qty_available >= self.min_qty_available else 'false'
        offer_id = item.sku or item.external_id or str(product.id)

        offer = etree.SubElement(offers_element, 'offer', id=offer_id, available=available)

        # Basic info
        if product.default_code:
            etree.SubElement(offer, 'vendorCode').text = product.default_code

        # URL (if website module installed)
        base_url = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        etree.SubElement(offer, 'url').text = f"{base_url}/shop/product/{product.id}"

        # Price
        price = item.price or 0
        if price > 0:
            etree.SubElement(offer, 'price').text = str(price)
        if item.price_original and item.price_original > price:
            etree.SubElement(offer, 'oldprice').text = str(item.price_original)

        etree.SubElement(offer, 'currencyId').text = self.currency_id.name

        # Category
        if item.marketplace_category_id:
            cat_id = item.marketplace_category_id.external_id or item.marketplace_category_id.id
            etree.SubElement(offer, 'categoryId').text = str(cat_id)

        # Images
        if product.image_1920:
            # Main image
            img_url = f"{base_url}/web/image/product.template/{product.id}/image_1920"
            etree.SubElement(offer, 'picture').text = img_url

        # Name and description
        name = item.name_override or product.name
        etree.SubElement(offer, 'name').text = name

        description = item.description_override or product.description_sale or ''
        if description:
            etree.SubElement(offer, 'description').text = description

        # Brand
        # `product_brand_id` дає OCA-модуль `product_brand`, якого немає ні в
        # ядрі, ні в залежностях: питаємо реєстр полів, а не об'єкт.
        if 'product_brand_id' in product._fields and product.product_brand_id:
            etree.SubElement(offer, 'vendor').text = product.product_brand_id.name

        # Stock quantity
        if item.qty_available > 0:
            etree.SubElement(offer, 'stock_quantity').text = str(int(item.qty_available))

        # Product attributes as params
        for attr_line in product.attribute_line_ids:
            for value in attr_line.value_ids:
                param = etree.SubElement(offer, 'param', name=attr_line.attribute_id.name)
                param.text = value.name

        return offer

    def _generate_xml_feed(self):
        """Generate generic XML feed."""
        # Same as YML for now, can be customized per marketplace
        return self._generate_yml_feed()


class MarketplacePricelistItem(models.Model):
    _name = 'marketplace.pricelist.item'
    _description = 'Marketplace Pricelist Item'
    _order = 'pricelist_id, product_tmpl_id'

    pricelist_id = fields.Many2one(
        'marketplace.pricelist',
        string='Pricelist',
        required=True,
        ondelete='cascade',
    )
    backend_id = fields.Many2one(
        related='pricelist_id.backend_id',
        store=True,
    )
    marketplace_type = fields.Selection(
        related='pricelist_id.marketplace_type',
        store=True,
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        help='Specific variant (if empty, uses template)',
    )
    active = fields.Boolean(
        default=True,
    )

    # === Identifiers ===
    external_id = fields.Char(
        string='External ID',
        index=True,
        help='Product ID on marketplace',
    )
    sku = fields.Char(
        string='SKU',
        compute='_compute_sku',
        store=True,
    )
    barcode = fields.Char(
        string='Barcode',
        related='product_tmpl_id.barcode',
    )

    # === Category ===
    marketplace_category_id = fields.Many2one(
        'marketplace.category',
        string='Marketplace Category',
    )

    # === Pricing ===
    price = fields.Float(
        string='Price',
        compute='_compute_price',
        store=True,
    )
    price_original = fields.Float(
        string='Original Price',
        help='Price before discount (for crossed-out price)',
    )
    price_promo = fields.Float(
        string='Promo Price',
        help='Special promotional price',
    )
    currency_id = fields.Many2one(
        related='pricelist_id.currency_id',
    )

    # === Stock ===
    qty_available = fields.Float(
        string='Available Qty',
        compute='_compute_qty_available',
    )
    qty_to_publish = fields.Float(
        string='Qty to Publish',
        help='Override quantity to publish (0 = use actual)',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        help='Warehouse for stock calculation (empty = all)',
    )

    # === Content Override ===
    name_override = fields.Char(
        string='Name Override',
    )
    description_override = fields.Text(
        string='Description Override',
    )
    image_urls = fields.Text(
        string='Image URLs',
        help='JSON array of image URLs',
    )

    # === Status ===
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending', 'Pending'),
            ('published', 'Published'),
            ('error', 'Error'),
        ],
        string='State',
        default='draft',
    )
    last_sync = fields.Datetime(
        string='Last Sync',
    )
    sync_error = fields.Text(
        string='Sync Error',
    )

    _product_pricelist_uniq = models.Constraint(
        'UNIQUE(pricelist_id, product_tmpl_id)',
        'Product already exists in this pricelist!',
    )
    _external_backend_uniq = models.Constraint(
        'UNIQUE(external_id, backend_id)',
        'External ID must be unique per backend!',
    )

    @api.depends('product_tmpl_id', 'product_id')
    def _compute_sku(self):
        for item in self:
            if item.product_id:
                item.sku = item.product_id.default_code or ''
            elif item.product_tmpl_id:
                item.sku = item.product_tmpl_id.default_code or ''
            else:
                item.sku = ''

    @api.depends('product_tmpl_id', 'product_id', 'pricelist_id.pricelist_id',
                 'pricelist_id.price_margin', 'pricelist_id.price_round',
                 'pricelist_id.min_price', 'price_promo')
    def _compute_price(self):
        for item in self:
            price = 0.0
            product = item.product_id or item.product_tmpl_id.product_variant_id

            if product and item.pricelist_id:
                pl = item.pricelist_id

                # Get base price
                if pl.pricelist_id:
                    price = pl.pricelist_id._get_product_price(product, 1.0)
                else:
                    price = product.lst_price

                # Apply margin
                if pl.price_margin:
                    price = price * (1 + pl.price_margin / 100)

                # Round
                if pl.price_round:
                    price = round(price / pl.price_round) * pl.price_round

                # Min price
                if pl.min_price and price < pl.min_price:
                    price = pl.min_price

            # Use promo price if set and lower
            if item.price_promo and item.price_promo < price:
                price = item.price_promo

            item.price = price

    def _compute_qty_available(self):
        for item in self:
            product = item.product_id or item.product_tmpl_id.product_variant_id

            if not product:
                item.qty_available = 0
                continue

            # Use override if set
            if item.qty_to_publish:
                item.qty_available = item.qty_to_publish
                continue

            # Calculate from stock
            warehouse = item.warehouse_id or item.pricelist_id.backend_id.warehouse_id

            if warehouse:
                # Get stock for specific warehouse
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', product.id),
                    ('location_id', 'child_of', warehouse.lot_stock_id.id),
                ])
                item.qty_available = sum(quants.mapped('quantity'))
            else:
                item.qty_available = product.qty_available

    def action_publish(self):
        """Mark items as pending for publication."""
        self.write({'state': 'pending'})

    def action_unpublish(self):
        """Mark items as draft."""
        self.write({'state': 'draft'})

    def action_sync(self):
        """Sync item to marketplace."""
        for item in self:
            try:
                item.backend_id._api_sync_stock([item])
                item.write({
                    'state': 'published',
                    'last_sync': fields.Datetime.now(),
                    'sync_error': False,
                })
            except Exception as e:
                item.write({
                    'state': 'error',
                    'sync_error': str(e),
                })
