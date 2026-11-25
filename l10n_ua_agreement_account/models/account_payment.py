from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        ondelete='restrict',
        index=True,
        copy=False,
        help='The agreement the payment was made under, for settlements by '
             'agreement.',
    )


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def _create_payments(self):
        """Проставити договір на платежі, якщо всі оплачувані рахунки — за одним."""
        payments = super()._create_payments()
        agreements = self.line_ids.mapped('move_id.l10n_ua_agreement_id')
        if len(agreements) == 1:
            payments.l10n_ua_agreement_id = agreements.id
        return payments
