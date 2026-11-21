from odoo import api, fields, models


MEAL_KIND = [
    ('breakfast', 'Сніданок'),
    ('lunch', 'Обід'),
    ('afternoon', 'Полуденок'),
    ('dinner', 'Вечеря'),
    ('snack', 'Перекус'),
]

AGE_GROUP = [
    ('zdo_1_3', 'ЗДО 1-3 роки'),
    ('zdo_3_6', 'ЗДО 3-6 років'),
    ('school_1_4', 'Школа 1-4 класи'),
    ('school_5_11', 'Школа 5-11 класи'),
    ('college_15_19', 'Коледж / ЗФПО 15-19 років'),
    ('other', 'Інше'),
]

# Age groups available on a menu (a menu is always for a concrete group).
MENU_AGE_GROUP = [item for item in AGE_GROUP if item[0] != 'other']


class L10nUaMealRecipe(models.Model):
    """Технологічна картка страви."""
    _name = 'l10n_ua.meal.recipe'
    _description = 'Технологічна картка страви'
    _order = 'name'

    name = fields.Char(string='Назва страви', required=True)
    code = fields.Char(string='Код')
    meal_kind = fields.Selection(MEAL_KIND, string='Тип прийому', default='lunch')
    age_group = fields.Selection(AGE_GROUP, string='Вікова група', default='zdo_3_6')
    yield_grams = fields.Float(string='Вихід порції, г', help='Маса готової порції')
    calories_kcal = fields.Float(string='Калорійність, ккал')
    protein_g = fields.Float(string='Білки, г')
    fat_g = fields.Float(string='Жири, г')
    carbohydrate_g = fields.Float(string='Вуглеводи, г')
    cooking_instructions = fields.Html(string='Технологія приготування')
    ingredient_ids = fields.One2many('l10n_ua.meal.recipe.ingredient', 'recipe_id',
                                       string='Інгредієнти')
    cost_per_portion = fields.Float(
        string='Собівартість порції', digits='Product Price',
        compute='_compute_cost_per_portion',
        help='Сума вартості інгредієнтів, пов\'язаних із товарами, за їхньою '
             'собівартістю (на одну порцію виходу).')
    active = fields.Boolean(default=True)

    @api.depends('ingredient_ids.cost')
    def _compute_cost_per_portion(self):
        for recipe in self:
            recipe.cost_per_portion = sum(recipe.ingredient_ids.mapped('cost'))

    def _get_product_consumption(self, factor=1.0):
        """Products needed for `factor` portions of the recipe.

        :return: dict {product.product: quantity in the product's UoM}
        """
        result = {}
        for ingredient in self.ingredient_ids.filtered('product_id'):
            qty = ingredient._get_qty_in_product_uom() * factor
            result[ingredient.product_id] = result.get(ingredient.product_id, 0.0) + qty
        return result


class L10nUaMealRecipeIngredient(models.Model):
    _name = 'l10n_ua.meal.recipe.ingredient'
    _description = 'Інгредієнт страви'
    _order = 'recipe_id, sequence'

    recipe_id = fields.Many2one('l10n_ua.meal.recipe', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    # Free-text name kept for backward compatibility and for ingredients that
    # are not (yet) linked to a product; filled from the product otherwise.
    name = fields.Char(string='Продукт', required=True)
    product_id = fields.Many2one(
        'product.product', string='Товар', ondelete='restrict', index='btree_not_null',
        help='Товар складу — потрібен для розрахунку собівартості та витрати продуктів.')
    quantity_g = fields.Float(string='Закладка нетто, г', required=True)
    gross_g = fields.Float(string='Брутто, г',
                            help='Маса до обробки/чистки. Корисно для розрахунку '
                                 'потреби у продуктах.')
    product_uom_id = fields.Many2one(
        'uom.uom', string='Од. виміру',
        compute='_compute_product_uom_id', store=True, readonly=False, precompute=True)
    product_qty = fields.Float(
        # 4 decimals: grams of an ingredient expressed in kg (55 g = 0.055 kg)
        string='Кількість', digits=(16, 4),
        compute='_compute_product_qty', store=True, readonly=False, precompute=True,
        help='Кількість товару на одну порцію в одиниці виміру рядка. Для вагових '
             'одиниць рахується з маси брутто (або нетто, якщо брутто не вказано).')
    cost = fields.Float(string='Вартість', digits='Product Price',
                        compute='_compute_cost')
    note = fields.Char(string='Примітка')

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            if line.product_id:
                line.product_uom_id = line.product_id.uom_id
            elif not line.product_uom_id:
                line.product_uom_id = False

    @api.depends('product_uom_id', 'gross_g', 'quantity_g')
    def _compute_product_qty(self):
        gram = self.env.ref('uom.product_uom_gram', raise_if_not_found=False)
        for line in self:
            uom = line.product_uom_id
            grams = line.gross_g or line.quantity_g
            if uom and gram and grams and uom._has_common_reference(gram):
                line.product_qty = gram._compute_quantity(grams, uom, round=False)
            else:
                # Non-weight unit (pcs, l, ...): entered manually.
                line.product_qty = line.product_qty or 0.0

    def _get_qty_in_product_uom(self):
        self.ensure_one()
        product_uom = self.product_id.uom_id
        uom = self.product_uom_id
        if not uom or not product_uom or uom == product_uom \
                or not uom._has_common_reference(product_uom):
            return self.product_qty
        return uom._compute_quantity(self.product_qty, product_uom, round=False)

    @api.depends('product_id', 'product_id.standard_price', 'product_qty', 'product_uom_id')
    def _compute_cost(self):
        for line in self:
            if line.product_id:
                line.cost = line._get_qty_in_product_uom() * line.product_id.standard_price
            else:
                line.cost = 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') and vals.get('product_id'):
                vals['name'] = self.env['product.product'].browse(vals['product_id']).name
        return super().create(vals_list)

    @api.model
    def _link_products_by_name(self):
        """Link unlinked ingredients to products with exactly the same name.

        Used by the 20.0.1.1.0 migration. The match is case-insensitive and
        must be unique; ambiguous or unmatched ingredients stay text-only.
        :return: recordset of the ingredients that were linked
        """
        Product = self.env['product.product'].with_context(active_test=True)
        ingredients = self.search([('product_id', '=', False)])
        linked = self.browse()
        by_name = {}
        for ingredient in ingredients:
            key = (ingredient.name or '').strip()
            if key:
                by_name.setdefault(key, self.browse())
                by_name[key] |= ingredient
        for name, group in by_name.items():
            pattern = name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            products = Product.search([('name', '=ilike', pattern)], limit=2)
            if len(products) == 1:
                group.write({'product_id': products.id})
                linked |= group
        return linked
