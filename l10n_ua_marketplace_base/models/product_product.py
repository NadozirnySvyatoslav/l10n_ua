from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_view_marketplace_items(self):
        """Delegate to template — required because product.product_normal_form_view
        inherits product_template_form_view in primary mode (Odoo 19), so the
        stat-button on the template form is also rendered on variant form.
        Strict view validation requires the method to exist on product.product."""
        return self.product_tmpl_id.action_view_marketplace_items()

    def action_add_to_marketplace(self):
        """Same as action_view_marketplace_items — delegate to template."""
        return self.product_tmpl_id.action_add_to_marketplace()
