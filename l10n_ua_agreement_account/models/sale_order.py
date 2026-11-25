from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _prepare_invoice(self):
        """Пробросити договір із замовлення у рахунок."""
        vals = super()._prepare_invoice()
        if self.l10n_ua_agreement_id:
            vals['l10n_ua_agreement_id'] = self.l10n_ua_agreement_id.id
        return vals
