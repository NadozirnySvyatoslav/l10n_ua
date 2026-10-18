from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _l10n_ua_printable_invoice(self):
        """The posted customer invoice of a confirmed order, the latest one; empty otherwise."""
        self.ensure_one()
        if self.state != 'sale':
            return self.env['account.move']
        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
        return invoices.sorted('id')[-1:]
