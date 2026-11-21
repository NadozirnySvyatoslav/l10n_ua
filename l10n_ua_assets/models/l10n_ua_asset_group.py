from odoo import fields, models


class L10nUaAssetGroup(models.Model):
    _name = 'l10n_ua.asset.group'
    _description = 'Fixed Asset Group (Tax Code)'
    _order = 'code'

    code = fields.Char(
        string='Code',
        required=True,
    )
    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
    )
    min_useful_life = fields.Integer(
        string='Min Useful Life (years)',
        help='Minimum useful life according to Tax Code',
    )
    description = fields.Text(
        string='Description',
        translate=True,
    )

    # --- Default accounts for monthly depreciation posting ---
    depreciation_journal_id = fields.Many2one(
        'account.journal',
        string='Журнал амортизації',
        domain="[('type', '=', 'general')]",
        help='Журнал за замовчуванням для проводок місячної амортизації',
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат (Дт)',
        help='Рахунок витрат на амортизацію за замовч. (23/91/92/93/94)',
    )
    depreciation_account_id = fields.Many2one(
        'account.account',
        string='Рахунок зносу (Кт 131)',
        help='Рахунок накопиченого зносу за замовч. (131)',
    )

    # --- Commissioning entry (Дт 10х / Кт 152) ---
    create_commission_move = fields.Boolean(
        string='Проводка введення в експлуатацію',
        help='При введенні ОЗ цієї групи в експлуатацію формувати проводку '
             'Дт 10х / Кт 152 (або інший рахунок джерела) на первісну вартість. '
             'Вимкніть, якщо первісна вартість потрапляє на 10х з рахунку '
             'постачальника чи вхідних залишків.',
    )
    fixed_asset_account_id = fields.Many2one(
        'account.account',
        string='Рахунок ОЗ (Дт 10х)',
        help='Рахунок обліку ОЗ за замовч. (103–109)',
    )
    commission_account_id = fields.Many2one(
        'account.account',
        string='Рахунок джерела (Кт 152/631)',
        help='Рахунок, з якого ОЗ надходить при введенні в експлуатацію '
             '(152 «Придбання ОЗ», 631 тощо)',
    )

    active = fields.Boolean(
        default=True,
    )

    _unique_code = models.Constraint(
        'UNIQUE(code)',
        'Asset group code must be unique!',
    )
