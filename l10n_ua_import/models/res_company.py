from odoo import fields, models

# Рахунки за замовчуванням (План рахунків П(С)БО, стоковий ua_psbo): перший
# знайдений префікс.
CUSTOMS_ACCOUNT_CODES = ('3771', '377', '642')
IMPORT_VAT_ACCOUNT_CODES = ('6441', '6412', '641')


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_import_journal_id = fields.Many2one(
        'account.journal', string='Import Customs Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help='Журнал проведень митної декларації на імпорт (ПДВ і митні платежі у собівартість).')
    l10n_ua_import_customs_account_id = fields.Many2one(
        'account.account', string='Customs Payments Account',
        help='Розрахунки з митницею: кредит на суму мита, акцизу, зборів і ПДВ з МД. Типово 377 '
             '(аванс, сплачений на рахунок митниці) або 642, якщо платежі обліковують як '
             'обов’язкові.')
    l10n_ua_import_vat_account_id = fields.Many2one(
        'account.account', string='Import VAT Account',
        help='Дебет на суму ПДВ з МД — податковий кредит (типово 6441).')
    l10n_ua_import_customs_partner_id = fields.Many2one(
        'res.partner', string='Default Customs Office',
        help='Митниця, на рахунок якої сплачують митні платежі, для нових митних декларацій.')

    def _l10n_ua_import_account(self, field, codes):
        """Рахунок з налаштувань компанії або перший за префіксом коду."""
        self.ensure_one()
        if self[field]:
            return self[field]
        Account = self.env['account.account'].with_company(self)
        for code in codes:
            account = Account.search([('code', '=like', f'{code}%'), ('company_ids', 'in', self.id),
                                      ('active', '=', True)], order='code', limit=1)
            if account:
                return account
        return Account

    def _l10n_ua_import_journal(self):
        self.ensure_one()
        return self.l10n_ua_import_journal_id or self.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', self.id)], limit=1)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    l10n_ua_import_journal_id = fields.Many2one(
        related='company_id.l10n_ua_import_journal_id', readonly=False)
    l10n_ua_import_customs_account_id = fields.Many2one(
        related='company_id.l10n_ua_import_customs_account_id', readonly=False)
    l10n_ua_import_vat_account_id = fields.Many2one(
        related='company_id.l10n_ua_import_vat_account_id', readonly=False)
    l10n_ua_import_customs_partner_id = fields.Many2one(
        related='company_id.l10n_ua_import_customs_partner_id', readonly=False)
