"""Акт звірки за конкретним договором (#208)."""

from odoo import fields, models


class ReconciliationActWizard(models.TransientModel):
    _inherit = 'l10n_ua.reconciliation.act.wizard'

    l10n_ua_agreement_id = fields.Many2one(
        'l10n_ua.agreement',
        string='Agreement',
        domain="[('commercial_partner_id', '=', partner_id)]",
        help='Limit the reconciliation act to one agreement. When empty, all '
             'settlements with the partner are reconciled.',
    )

    def _get_move_line_domain(self):
        """Додати фільтр за договором."""
        domain = super()._get_move_line_domain()
        if self.l10n_ua_agreement_id:
            domain.append(('l10n_ua_agreement_id', '=', self.l10n_ua_agreement_id.id))
        return domain

    def _get_opening_balance(self, account_types):
        """Врахувати договір у розрахунку вхідного сальдо."""
        if not self.l10n_ua_agreement_id:
            return super()._get_opening_balance(account_types)
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.balance), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE aml.partner_id = %s
              AND am.state = 'posted'
              AND aml.date < %s
              AND aa.account_type IN %s
              AND aml.l10n_ua_agreement_id = %s
        """, (self.partner_id.id, self.date_from, tuple(account_types),
              self.l10n_ua_agreement_id.id))
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0
