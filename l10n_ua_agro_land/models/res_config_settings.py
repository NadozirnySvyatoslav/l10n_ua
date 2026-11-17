from odoo import _, api, fields, models
from odoo.tools import float_compare

# Ставка ПДФО з оренди землі/паїв (пп. 170.1.4, п. 167.1 ПКУ, ред. Закону № 5025-IX).
LAND_RENT_PDFO_RATE = 18.0


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_ua_agro_rent_journal_id = fields.Many2one(
        related='company_id.l10n_ua_agro_rent_journal_id', readonly=False)
    l10n_ua_agro_rent_expense_account_id = fields.Many2one(
        related='company_id.l10n_ua_agro_rent_expense_account_id', readonly=False)
    l10n_ua_agro_rent_payable_account_id = fields.Many2one(
        related='company_id.l10n_ua_agro_rent_payable_account_id', readonly=False)
    l10n_ua_agro_pdfo_account_id = fields.Many2one(
        related='company_id.l10n_ua_agro_pdfo_account_id', readonly=False)
    l10n_ua_agro_military_account_id = fields.Many2one(
        related='company_id.l10n_ua_agro_military_account_id', readonly=False)
    l10n_ua_agro_in_kind_income_account_id = fields.Many2one(
        related='company_id.l10n_ua_agro_in_kind_income_account_id', readonly=False)
    l10n_ua_agro_pdfo_rate = fields.Float(
        related='company_id.l10n_ua_agro_pdfo_rate', readonly=False)
    l10n_ua_agro_military_rate = fields.Float(
        related='company_id.l10n_ua_agro_military_rate', readonly=False)

    @api.onchange('l10n_ua_agro_pdfo_rate')
    def _onchange_l10n_ua_agro_pdfo_rate(self):
        """Лише попередження: ставку не блокуємо — її може змінити новий закон."""
        if float_compare(self.l10n_ua_agro_pdfo_rate, LAND_RENT_PDFO_RATE, precision_digits=2):
            return {'warning': {
                'title': _('PIT rate on land rent'),
                'message': _(
                    'Check the rate: personal income tax on land and land share rent is 18% '
                    '(PTC 170.1.4, 167.1). The 5% rate from 23.10.2026 (Law No. 5025-IX) '
                    'applies only to residential/non-residential real estate.'),
            }}
