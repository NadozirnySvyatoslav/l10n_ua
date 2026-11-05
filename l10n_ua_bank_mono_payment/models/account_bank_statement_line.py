from odoo import api, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # A payment prepared through the corporate API comes back in the
        # statement with the external reference it was sent with.
        refs = [ref for ref in lines.mapped('l10n_ua_mono_external_ref') if ref]
        if refs:
            self.env['l10n_ua.bank.payment.line'].sudo()._mono_match_statement_lines(
                lines.filtered('l10n_ua_mono_external_ref'))
        return lines
