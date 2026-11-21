import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Link existing text-only recipe ingredients to products by exact name.

    Ingredients without a unique product match keep their text name and
    stay unlinked.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Ingredient = env['l10n_ua.meal.recipe.ingredient']
    total = Ingredient.search_count([('product_id', '=', False)])
    linked = Ingredient._link_products_by_name()
    _logger.info('l10n_ua_education_meals: linked %s of %s recipe ingredients to products',
                 len(linked), total)
