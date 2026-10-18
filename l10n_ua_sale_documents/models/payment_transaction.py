from odoo import models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _invoice_sale_orders(self):
        """No automatic invoices from payments of providers in test mode.

        A test payment must not put income into the books. The order is still confirmed and the
        rest of the post-processing runs as usual; only the invoice creation is skipped.
        """
        return super(
            PaymentTransaction, self.filtered(lambda tx: tx.provider_id.state != 'test')
        )._invoice_sale_orders()
