from odoo import api, fields, models

from .l10n_ua_meal_recipe import MENU_AGE_GROUP


class L10nUaMealMenu(models.Model):
    """Меню (один день)."""
    _name = 'l10n_ua.meal.menu'
    _description = 'Меню на день'
    _order = 'menu_date desc, age_group'

    name = fields.Char(string='Назва', compute='_compute_name', store=True)
    menu_date = fields.Date(string='Дата', required=True, default=fields.Date.context_today)
    age_group = fields.Selection(MENU_AGE_GROUP, string='Вікова група', required=True)
    company_id = fields.Many2one('res.company', required=True,
                                   default=lambda self: self.env.company)
    line_ids = fields.One2many('l10n_ua.meal.menu.line', 'menu_id', string='Страви',
                                 copy=True)
    total_calories = fields.Float(string='Усього ккал',
                                    compute='_compute_totals', store=True)
    total_protein = fields.Float(string='Усього білки, г',
                                   compute='_compute_totals', store=True)
    total_fat = fields.Float(string='Усього жири, г',
                               compute='_compute_totals', store=True)
    total_carbohydrate = fields.Float(string='Усього вуглеводи, г',
                                        compute='_compute_totals', store=True)
    portion_count = fields.Integer(
        string='Кількість порцій',
        help='Кількість дітей (порцій), на яку готується меню. Використовується '
             'для розрахунку загальної вартості та витрати продуктів.')
    cost_per_child = fields.Float(string='Вартість на 1 дитину', digits='Product Price',
                                  compute='_compute_cost')
    total_cost = fields.Float(string='Загальна вартість', digits='Product Price',
                              compute='_compute_cost')
    consumption_ids = fields.One2many(
        'l10n_ua.meal.menu.consumption', 'menu_id', string='Витрата продуктів',
        copy=False)
    state = fields.Selection([
        ('draft', 'Чернетка'),
        ('approved', 'Затверджено'),
    ], default='draft', required=True)
    note = fields.Text(string='Примітки')

    @api.depends('menu_date', 'age_group')
    def _compute_name(self):
        for rec in self:
            label = dict(self._fields['age_group'].selection).get(rec.age_group) or ''
            rec.name = f'{rec.menu_date} — {label}' if rec.menu_date else label

    @api.depends('line_ids.calories', 'line_ids.protein', 'line_ids.fat',
                  'line_ids.carbohydrate')
    def _compute_totals(self):
        for rec in self:
            rec.total_calories = sum(rec.line_ids.mapped('calories'))
            rec.total_protein = sum(rec.line_ids.mapped('protein'))
            rec.total_fat = sum(rec.line_ids.mapped('fat'))
            rec.total_carbohydrate = sum(rec.line_ids.mapped('carbohydrate'))

    @api.depends('line_ids.cost', 'portion_count')
    def _compute_cost(self):
        for rec in self:
            rec.cost_per_child = sum(rec.line_ids.mapped('cost'))
            rec.total_cost = rec.cost_per_child * (rec.portion_count or 0)

    def _get_product_consumption(self):
        """Total products needed for the menu (`portion_count` portions).

        :return: dict {product.product: quantity in the product's UoM}
        """
        self.ensure_one()
        result = {}
        for line in self.line_ids:
            factor = line._get_recipe_factor() * (self.portion_count or 0)
            for product, qty in line.recipe_id._get_product_consumption(factor).items():
                result[product] = result.get(product, 0.0) + qty
        return result

    def action_compute_consumption(self):
        """(Re)build the product consumption lines of the menu."""
        for rec in self:
            rec.consumption_ids.unlink()
            rec.consumption_ids = [
                fields.Command.create({
                    'product_id': product.id,
                    'quantity': qty,
                    'unit_cost': product.standard_price,
                })
                for product, qty in sorted(rec._get_product_consumption().items(),
                                           key=lambda item: item[0].display_name)
            ]

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})


class L10nUaMealMenuLine(models.Model):
    _name = 'l10n_ua.meal.menu.line'
    _description = 'Страва в меню'
    _order = 'menu_id, meal_kind, sequence'

    menu_id = fields.Many2one('l10n_ua.meal.menu', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    meal_kind = fields.Selection([
        ('breakfast', 'Сніданок'),
        ('lunch', 'Обід'),
        ('afternoon', 'Полуденок'),
        ('dinner', 'Вечеря'),
        ('snack', 'Перекус'),
    ], string='Тип прийому', required=True, default='lunch')
    recipe_id = fields.Many2one('l10n_ua.meal.recipe', string='Страва', required=True)
    portion_grams = fields.Float(
        string='Порція, г',
        compute='_compute_recipe_data', store=True, readonly=False)
    calories = fields.Float(
        string='ккал', compute='_compute_recipe_data', store=True, readonly=False)
    protein = fields.Float(
        string='Б, г', compute='_compute_recipe_data', store=True, readonly=False)
    fat = fields.Float(
        string='Ж, г', compute='_compute_recipe_data', store=True, readonly=False)
    carbohydrate = fields.Float(
        string='В, г', compute='_compute_recipe_data', store=True, readonly=False)

    cost = fields.Float(string='Вартість', digits='Product Price',
                        compute='_compute_cost',
                        help='Собівартість однієї порції (з урахуванням маси порції).')

    def _get_recipe_factor(self):
        """Share of the recipe yield in this line's portion (1.0 = as in the recipe)."""
        self.ensure_one()
        recipe = self.recipe_id
        if recipe.yield_grams and self.portion_grams:
            return self.portion_grams / recipe.yield_grams
        return 1.0

    @api.depends('recipe_id.cost_per_portion', 'recipe_id.yield_grams', 'portion_grams')
    def _compute_cost(self):
        for line in self:
            line.cost = line.recipe_id.cost_per_portion * line._get_recipe_factor() \
                if line.recipe_id else 0.0

    @api.depends('recipe_id')
    def _compute_recipe_data(self):
        for line in self:
            if line.recipe_id:
                line.portion_grams = line.recipe_id.yield_grams
                line.calories = line.recipe_id.calories_kcal
                line.protein = line.recipe_id.protein_g
                line.fat = line.recipe_id.fat_g
                line.carbohydrate = line.recipe_id.carbohydrate_g


class L10nUaMealMenuConsumption(models.Model):
    """Product consumption of a menu (built by "Розрахувати витрату")."""
    _name = 'l10n_ua.meal.menu.consumption'
    _description = 'Витрата продуктів за меню'
    _order = 'menu_id, product_id'

    menu_id = fields.Many2one('l10n_ua.meal.menu', required=True, ondelete='cascade',
                              index=True)
    product_id = fields.Many2one('product.product', string='Товар', required=True,
                                 ondelete='restrict')
    uom_id = fields.Many2one(related='product_id.uom_id', string='Од. виміру')
    quantity = fields.Float(string='Кількість', digits=(16, 4))
    unit_cost = fields.Float(string='Ціна за од.', digits='Product Price')
    cost = fields.Float(string='Вартість', digits='Product Price',
                        compute='_compute_cost', store=True)

    @api.depends('quantity', 'unit_cost')
    def _compute_cost(self):
        for line in self:
            line.cost = line.quantity * line.unit_cost
