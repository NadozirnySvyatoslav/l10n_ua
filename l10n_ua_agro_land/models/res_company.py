from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_agro_rent_journal_id = fields.Many2one(
        'account.journal', string='Land Rent Journal',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]")
    l10n_ua_agro_rent_expense_account_id = fields.Many2one(
        'account.account', string='Land Rent Expense Account',
        help='Рахунок витрат на орендну плату: 23 (виробництво) або 91.')
    l10n_ua_agro_rent_payable_account_id = fields.Many2one(
        'account.account', string='Land Rent Payable Account',
        help='Розрахунки з орендодавцями — 685.')
    l10n_ua_agro_pdfo_account_id = fields.Many2one(
        'account.account', string='Personal Income Tax Account',
        help='Розрахунки за ПДФО — 6411.')
    l10n_ua_agro_military_account_id = fields.Many2one(
        'account.account', string='Military Levy Account',
        help='Розрахунки за військовим збором — 642 (6415).')
    l10n_ua_agro_in_kind_income_account_id = fields.Many2one(
        'account.account', string='In-kind Payment Income Account',
        help='Дохід від реалізації інших оборотних активів — 712.')
    l10n_ua_agro_pdfo_rate = fields.Float(
        string='PIT Rate (%)', default=18.0,
        help='Оренда земельних ділянок, земельних часток (паїв), майнових паїв — 18 % '
             '(пп. 170.1.4, п. 167.1 ПКУ). Ставка 5 % з 23.10.2026 (Закон № 5025-IX) '
             'стосується лише житлової/нежитлової нерухомості і до землі НЕ застосовується.')
    l10n_ua_agro_military_rate = fields.Float(string='Military Levy Rate (%)', default=5.0)

    def _l10n_ua_agro_account(self, field, prefixes):
        """Рахунок з налаштувань компанії, інакше перший за префіксом коду."""
        self.ensure_one()
        if self[field]:
            return self[field]
        Account = self.env['account.account']
        for prefix in prefixes:
            account = Account.search([
                ('code', '=like', prefix + '%'),
                ('company_ids', 'in', self.id),
                ('active', '=', True),
            ], order='code', limit=1)
            if account:
                return account
        return Account
