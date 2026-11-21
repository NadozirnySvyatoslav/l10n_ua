"""Tests for issue #632: ingredients linked to products, costs, consumption, age groups."""
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install', 'l10n_ua_education_meals')
class TestMealsProducts(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kg = cls.env.ref('uom.product_uom_kgm')
        cls.gram = cls.env.ref('uom.product_uom_gram')
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.potato = cls.env['product.product'].create({
            'name': 'Картопля (тест)', 'uom_id': cls.kg.id, 'standard_price': 20.0,
        })
        cls.egg = cls.env['product.product'].create({
            'name': 'Яйце куряче (тест)', 'uom_id': cls.unit.id, 'standard_price': 6.0,
        })
        cls.recipe = cls.env['l10n_ua.meal.recipe'].create({
            'name': 'Картопляна запіканка',
            'yield_grams': 200,
            'ingredient_ids': [
                (0, 0, {'product_id': cls.potato.id, 'gross_g': 250, 'quantity_g': 200}),
                (0, 0, {'product_id': cls.egg.id, 'quantity_g': 50, 'product_qty': 1}),
                (0, 0, {'name': 'Сіль', 'quantity_g': 2}),
            ],
        })

    def test_ingredient_product_qty_uom_cost(self):
        potato_line, egg_line, salt_line = self.recipe.ingredient_ids
        # name filled from the product, UoM from the product
        self.assertEqual(potato_line.name, 'Картопля (тест)')
        self.assertEqual(potato_line.product_uom_id, self.kg)
        # weight UoM: quantity derived from the gross mass, 250 g = 0.25 kg
        self.assertAlmostEqual(potato_line.product_qty, 0.25)
        self.assertAlmostEqual(potato_line.cost, 5.0)
        # piece UoM: quantity is entered manually
        self.assertEqual(egg_line.product_uom_id, self.unit)
        self.assertAlmostEqual(egg_line.product_qty, 1.0)
        self.assertAlmostEqual(egg_line.cost, 6.0)
        # text-only ingredient (backward compatible): no cost
        self.assertFalse(salt_line.product_id)
        self.assertEqual(salt_line.name, 'Сіль')
        self.assertEqual(salt_line.cost, 0.0)
        self.assertAlmostEqual(self.recipe.cost_per_portion, 11.0)

    def test_ingredient_in_other_weight_uom(self):
        line = self.recipe.ingredient_ids[0]
        line.product_uom_id = self.gram
        self.assertAlmostEqual(line.product_qty, 250.0)
        # cost still in the product's UoM (kg): 0.25 kg * 20
        self.assertAlmostEqual(line.cost, 5.0)
        self.potato.standard_price = 40.0
        self.assertAlmostEqual(line.cost, 10.0)

    def test_ingredient_form_onchange(self):
        with Form(self.recipe) as recipe_form:
            with recipe_form.ingredient_ids.new() as ing:
                ing.product_id = self.potato
                ing.quantity_g = 100
                self.assertEqual(ing.name, 'Картопля (тест)')
                self.assertEqual(ing.product_uom_id, self.kg)
                self.assertAlmostEqual(ing.product_qty, 0.1)

    def test_menu_cost_and_consumption(self):
        menu = self.env['l10n_ua.meal.menu'].create({
            'menu_date': '2026-09-01',
            'age_group': 'zdo_3_6',
            'portion_count': 20,
            'line_ids': [(0, 0, {'recipe_id': self.recipe.id, 'meal_kind': 'lunch'})],
        })
        line = menu.line_ids
        self.assertEqual(line.portion_grams, 200)
        self.assertAlmostEqual(line.cost, 11.0)
        self.assertAlmostEqual(menu.cost_per_child, 11.0)
        self.assertAlmostEqual(menu.total_cost, 220.0)
        # half a portion -> half the cost and consumption
        line.portion_grams = 100
        self.assertAlmostEqual(menu.cost_per_child, 5.5)
        consumption = menu._get_product_consumption()
        self.assertAlmostEqual(consumption[self.potato], 0.25 * 0.5 * 20)
        self.assertAlmostEqual(consumption[self.egg], 1 * 0.5 * 20)
        self.assertEqual(len(consumption), 2)  # text-only salt is not a product

        menu.action_compute_consumption()
        by_product = {c.product_id: c for c in menu.consumption_ids}
        self.assertAlmostEqual(by_product[self.potato].quantity, 2.5)
        self.assertEqual(by_product[self.potato].uom_id, self.kg)
        self.assertAlmostEqual(by_product[self.potato].cost, 50.0)
        self.assertAlmostEqual(by_product[self.egg].cost, 60.0)
        self.assertAlmostEqual(sum(menu.consumption_ids.mapped('cost')), menu.total_cost)
        # recomputation replaces the lines
        menu.portion_count = 10
        menu.action_compute_consumption()
        self.assertEqual(len(menu.consumption_ids), 2)
        self.assertAlmostEqual(
            menu.consumption_ids.filtered(lambda c: c.product_id == self.potato).quantity, 1.25)

    def test_college_age_group(self):
        Menu = self.env['l10n_ua.meal.menu']
        Recipe = self.env['l10n_ua.meal.recipe']
        self.assertIn('college_15_19', dict(Menu._fields['age_group'].selection))
        self.assertIn('college_15_19', dict(Recipe._fields['age_group'].selection))
        self.assertNotIn('other', dict(Menu._fields['age_group'].selection))
        menu = Menu.create({'menu_date': '2026-09-01', 'age_group': 'college_15_19'})
        self.assertIn('Коледж / ЗФПО 15-19 років', menu.name)

    def test_link_products_by_name(self):
        Ingredient = self.env['l10n_ua.meal.recipe.ingredient']
        Product = self.env['product.product']
        beet = Product.create({'name': 'Буряк столовий (тест)', 'uom_id': self.kg.id})
        Product.create({'name': 'Морква (тест)'})
        Product.create({'name': 'морква (тест)'})
        recipe = self.env['l10n_ua.meal.recipe'].create({
            'name': 'Вінегрет',
            'ingredient_ids': [
                (0, 0, {'name': 'буряк столовий (ТЕСТ) ', 'quantity_g': 40, 'gross_g': 50}),
                (0, 0, {'name': 'Морква (тест)', 'quantity_g': 20}),  # ambiguous
                (0, 0, {'name': 'Олія_100%', 'quantity_g': 5}),  # no match
            ],
        })
        beet_line, carrot_line, oil_line = recipe.ingredient_ids
        linked = Ingredient._link_products_by_name()
        self.assertIn(beet_line, linked)
        self.assertEqual(beet_line.product_id, beet)
        self.assertEqual(beet_line.name, 'буряк столовий (ТЕСТ) ')  # text kept
        self.assertEqual(beet_line.product_uom_id, self.kg)
        self.assertAlmostEqual(beet_line.product_qty, 0.05)
        self.assertFalse(carrot_line.product_id)
        self.assertFalse(oil_line.product_id)
        self.assertFalse(linked & (carrot_line | oil_line))
