from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero


def duval_weight(net, moisture, impurity, base_moisture, base_impurity):
    """Залікова маса за формулою Дюваля.

    m = net × (100 − З) × (100 − В) / ((100 − Зб) × (100 − Вб)),
    де фактичні показники, кращі за базисні, прирівнюються до базисних
    (без надбавки за якість)."""
    moisture = max(moisture or 0.0, base_moisture or 0.0)
    impurity = max(impurity or 0.0, base_impurity or 0.0)
    if moisture >= 100 or impurity >= 100:
        return 0.0
    return net * (100 - impurity) * (100 - moisture) / (
        (100 - (base_impurity or 0.0)) * (100 - (base_moisture or 0.0)))


class AgroHarvestReceipt(models.Model):
    """Реєстр завезення з поля (вагова картка): зважування, аналіз
    лабораторії й залікова маса, яку оприбутковують у партію."""
    _name = 'l10n_ua.agro.harvest.receipt'
    _description = 'Harvest Receipt'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(default='/', copy=False, readonly=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now, tracking=True)
    planting_id = fields.Many2one(
        'l10n_ua.agro.planting', string='Planting', required=True, index=True, tracking=True,
        domain="[('company_id', '=', company_id)]")
    field_id = fields.Many2one(related='planting_id.field_id', store=True, index=True)
    season_id = fields.Many2one(related='planting_id.season_id', store=True, index=True)
    crop_id = fields.Many2one(related='planting_id.crop_id', store=True, index=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        compute='_compute_product_id', store=True, readonly=False, precompute=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    vehicle = fields.Char(string='Vehicle')
    driver = fields.Char(string='Driver')
    combine_operator = fields.Char(string='Combine Operator', help='Комбайнер, з бункера якого завантажено машину.')
    weigher_id = fields.Many2one(
        'res.users', string='Weigher', default=lambda self: self.env.user,
        help='Хто зважив машину й прийняв зерно (завідувач току, ваговий).')
    location_dest_id = fields.Many2one(
        'stock.location', string='Storage', required=True,
        domain="[('usage', '=', 'internal'), ('company_id', 'in', (company_id, False))]",
        default=lambda self: self._default_location(),
        help='Власний склад / тік або місце зберігання на елеваторі.')
    gross_weight = fields.Float(string='Gross (kg)', digits=(16, 1), tracking=True)
    tare_weight = fields.Float(string='Tare (kg)', digits=(16, 1), tracking=True)
    net_weight = fields.Float(string='Net (kg)', digits=(16, 1), compute='_compute_weights', store=True)
    moisture = fields.Float(string='Moisture (%)', digits=(5, 2), tracking=True)
    impurity = fields.Float(string='Impurity (%)', digits=(5, 2), tracking=True)
    grain_impurity = fields.Float(string='Grain Impurity (%)', digits=(5, 2))
    test_weight = fields.Float(string='Test Weight (g/l)', digits=(6, 1))
    oil_content = fields.Float(string='Oil Content (%)', digits=(5, 2))
    protein = fields.Float(string='Protein (%)', digits=(5, 2))
    base_moisture = fields.Float(
        string='Base Moisture (%)', digits=(5, 2), compute='_compute_basis', store=True, readonly=False, precompute=True)
    base_impurity = fields.Float(
        string='Base Impurity (%)', digits=(5, 2), compute='_compute_basis', store=True, readonly=False, precompute=True)
    credit_weight = fields.Float(
        string='Credit Weight (kg)', digits=(16, 1), compute='_compute_weights', store=True,
        help='Залікова маса за формулою Дюваля — оприбутковується на склад.')
    weight_loss = fields.Float(string='Loss (kg)', digits=(16, 1), compute='_compute_weights', store=True)
    received_qty = fields.Float(
        string='Received', digits='Product Unit', readonly=True, copy=False,
        help='Оприбутковано на склад в одиниці виміру товару (з її точністю). Зерно краще вести в кг.')
    uom_id = fields.Many2one(related='product_id.uom_id')
    lot_id = fields.Many2one('stock.lot', string='Batch', readonly=True, copy=False, index=True)
    move_id = fields.Many2one('stock.move', string='Stock Move', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Received'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    note = fields.Text()

    @api.model
    def _default_location(self):
        company = self.env.company
        return company.l10n_ua_agro_harvest_location_id or self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1).lot_stock_id

    # від planting_id, а не related crop_id: related ще не пораховано на precompute
    @api.depends('planting_id.crop_id')
    def _compute_product_id(self):
        for receipt in self:
            if receipt.planting_id.crop_id.product_id:
                receipt.product_id = receipt.planting_id.crop_id.product_id

    @api.depends('planting_id.crop_id')
    def _compute_basis(self):
        for receipt in self:
            crop = receipt.planting_id.crop_id
            receipt.base_moisture = crop.base_moisture
            receipt.base_impurity = crop.base_impurity

    @api.depends('gross_weight', 'tare_weight', 'moisture', 'impurity', 'base_moisture', 'base_impurity')
    def _compute_weights(self):
        for receipt in self:
            receipt.net_weight = max(receipt.gross_weight - receipt.tare_weight, 0.0)
            receipt.credit_weight = round(duval_weight(
                receipt.net_weight, receipt.moisture, receipt.impurity,
                receipt.base_moisture, receipt.base_impurity), 1)
            receipt.weight_loss = receipt.net_weight - receipt.credit_weight

    @api.constrains('gross_weight', 'tare_weight', 'moisture', 'impurity')
    def _check_values(self):
        for receipt in self:
            if receipt.tare_weight > receipt.gross_weight:
                raise ValidationError(self.env._('The tare cannot exceed the gross weight.'))
            if not (0 <= receipt.moisture < 100 and 0 <= receipt.impurity < 100):
                raise ValidationError(self.env._('Moisture and impurity must be between 0 and 100 %.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'l10n_ua.agro.harvest.receipt') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(receipt.state == 'done' for receipt in self):
            raise UserError(self.env._('Cancel the harvest receipt before deleting it.'))
        return super().unlink()

    # --- Оприбуткування ---

    def _lot_name(self):
        self.ensure_one()
        return '%s-%s-%s' % (self.season_id.year, self.crop_id.code or self.crop_id.id,
                             self.field_id.code or self.field_id.id)

    def _get_or_create_lot(self):
        self.ensure_one()
        Lot = self.env['stock.lot']
        name = self._lot_name()
        lot = Lot.search([('name', '=', name), ('product_id', '=', self.product_id.id),
                          ('company_id', '=', self.company_id.id)], limit=1)
        return lot or Lot.create({
            'name': name, 'product_id': self.product_id.id, 'company_id': self.company_id.id,
            'l10n_ua_agro_planting_id': self.planting_id.id})

    def _source_location(self):
        self.ensure_one()
        return self.product_id.with_company(self.company_id).property_stock_production

    def action_done(self):
        for receipt in self:
            if receipt.state != 'draft':
                continue
            if float_is_zero(receipt.credit_weight, precision_digits=1):
                raise UserError(self.env._('Weigh the vehicle first: the credit weight is zero.'))
            if not receipt.product_id:
                raise UserError(self.env._('Set the product the crop is received as.'))
            receipt.sudo()._receive()
            receipt.state = 'done'
        return True

    def _receive(self):
        self.ensure_one()
        product = self.product_id
        kg = self.env.ref('uom.product_uom_kgm')
        quantity = kg._compute_quantity(self.credit_weight, product.uom_id, rounding_method='HALF-UP')
        lot = self._get_or_create_lot() if product.tracking == 'lot' else self.env['stock.lot']
        source = self._source_location()
        move = self.env['stock.move'].create({
            'product_id': product.id,
            'product_uom_qty': quantity,
            'product_uom': product.uom_id.id,
            'location_id': source.id,
            'location_dest_id': self.location_dest_id.id,
            'company_id': self.company_id.id,
            'origin': self.name,
        })
        # зв'язок до проведення руху: вартість вхідного руху (stock_account)
        # рахується в _action_done і може братися з оприбуткування
        self.move_id = move
        move._action_confirm()
        move._action_assign()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'quantity': quantity,
            'location_id': source.id,
            'location_dest_id': self.location_dest_id.id,
            'lot_id': lot.id,
            'company_id': self.company_id.id,
        })
        move.picked = True
        move._action_done()
        self.write({'move_id': move.id, 'lot_id': lot.id, 'received_qty': move.quantity})

    def action_cancel(self):
        for receipt in self.filtered(lambda r: r.state == 'done' and r.move_id):
            move = receipt.move_id
            available = self.env['stock.quant'].sudo()._get_available_quantity(
                move.product_id, move.location_dest_id, lot_id=receipt.lot_id or None, strict=True)
            if available < move.quantity - move.product_uom.rounding:
                raise UserError(self.env._(
                    'The grain of %(receipt)s has already left the storage: only %(available)s of '
                    '%(quantity)s is left, so the receipt cannot be cancelled.',
                    receipt=receipt.name, available=available, quantity=move.quantity))
            receipt.sudo()._return_move()
        self.write({'state': 'cancel'})

    def _return_move(self):
        self.ensure_one()
        move = self.move_id
        back = self.env['stock.move'].create({
            'product_id': move.product_id.id,
            'product_uom_qty': move.quantity,
            'product_uom': move.product_uom.id,
            'location_id': move.location_dest_id.id,
            'location_dest_id': move.location_id.id,
            'company_id': move.company_id.id,
            'origin': self.name,
            'origin_returned_move_id': move.id,
        })
        back._action_confirm()
        back._action_assign()
        back.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': back.id,
            'product_id': move.product_id.id,
            'product_uom_id': move.product_uom.id,
            'quantity': move.quantity,
            'location_id': move.location_dest_id.id,
            'location_dest_id': move.location_id.id,
            'lot_id': self.lot_id.id,
            'company_id': move.company_id.id,
        })
        back.picked = True
        back._action_done()

    # --- Друк: реєстри ф. № 77 / № 78 ---

    def _print_registers(self, by_vehicle=True):
        """Групи для реєстрів: відправки (ф. № 77) — машина × день,
        приймання (ф. № 78) — день × місце зберігання."""
        groups = {}
        receipts = self.filtered(lambda r: r.state != 'cancel').sorted(lambda r: (r.date, r.id))
        for receipt in receipts:
            day = fields.Datetime.context_timestamp(receipt, receipt.date).date()
            key = (day, receipt.vehicle or '', receipt.driver or '') if by_vehicle \
                else (day, receipt.location_dest_id)
            groups.setdefault(key, self.browse())
            groups[key] |= receipt
        return [{'key': key, 'day': key[0], 'receipts': recs,
                 'net': sum(recs.mapped('net_weight')), 'credit': sum(recs.mapped('credit_weight'))}
                for key, recs in groups.items()]

    def action_draft(self):
        for receipt in self:
            if receipt.state != 'cancel':
                raise UserError(self.env._('Only a cancelled receipt can be reset to draft.'))
        self.write({'state': 'draft', 'move_id': False, 'lot_id': False, 'received_qty': 0.0})
