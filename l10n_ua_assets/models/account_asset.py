"""Ukrainian fixed assets (Основні засоби) — standalone model."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import date_utils


class L10nUaAsset(models.Model):
    _name = 'l10n_ua.asset'
    _description = 'Основний засіб'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'acquisition_date desc, id desc'

    name = fields.Char(
        string='Найменування',
        required=True,
        tracking=True,
    )
    inventory_number = fields.Char(
        string='Інвентарний номер',
        tracking=True,
    )
    acquisition_date = fields.Date(
        string='Дата придбання',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    original_value = fields.Monetary(
        string='Первісна вартість',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    salvage_value = fields.Monetary(
        string='Ліквідаційна вартість',
        currency_field='currency_id',
        help='Очікувана вартість при вибутті',
    )

    # --- Classification ---
    group_id = fields.Many2one(
        'l10n_ua.asset.group',
        string='Група ОЗ',
        help='Група ОЗ згідно Податкового кодексу (1-16)',
    )

    # --- Depreciation parameters ---
    depreciation_method = fields.Selection(
        selection=[
            ('straight_line', 'Прямолінійний'),
            ('declining_balance', 'Зменшення залишку'),
            ('production', 'Виробничий'),
            ('cumulative', 'Кумулятивний'),
        ],
        string='Метод амортизації',
        default='straight_line',
        tracking=True,
    )
    useful_life = fields.Integer(
        string='Строк корисного використання (міс.)',
        help='Строк корисного використання у місяцях',
    )
    annual_depreciation_rate = fields.Float(
        string='Річна норма амортизації (%)',
        help='Для методу зменшення залишку. Якщо 0 — '
             'розраховується як 2/строк_років (подвійно-зменшуваний).',
    )
    production_capacity = fields.Float(
        string='Виробнича потужність',
        help='Загальна очікувана кількість одиниць продукції (для виробничого методу)',
    )
    produced_units = fields.Float(
        string='Вироблено одиниць',
        help='Кількість вироблених одиниць на поточний момент',
    )

    # --- State ---
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('open', 'В експлуатації'),
            ('paused', 'Призупинено'),
            ('close', 'Списано'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )

    # --- Commissioning ---
    commission_date = fields.Date(
        string='Дата введення в експлуатацію',
        tracking=True,
    )
    commission_act_number = fields.Char(
        string='№ акту введення',
        copy=False,
    )
    responsible_id = fields.Many2one(
        'hr.employee',
        string='МВО',
        help='Матеріально відповідальна особа',
    )
    location = fields.Char(
        string='Місцезнаходження',
    )

    # --- Write-off ---
    writeoff_act_number = fields.Char(
        string='№ акту списання',
        copy=False,
    )
    writeoff_date = fields.Date(
        string='Дата списання',
    )
    writeoff_reason = fields.Text(
        string='Причина списання',
    )

    # --- Company / Currency ---
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )

    # --- Depreciation board ---
    depreciation_line_ids = fields.One2many(
        'l10n_ua.asset.depreciation',
        'asset_id',
        string='Амортизаційні нарахування',
    )

    # --- Revaluation history ---
    revaluation_line_ids = fields.One2many(
        'l10n_ua.asset.revaluation.line',
        'asset_id',
        string='Історія переоцінок',
    )
    revaluation_count = fields.Integer(
        compute='_compute_revaluation_count',
        string='Кількість переоцінок',
    )
    cumulative_revaluation_balance = fields.Monetary(
        string='Баланс переоцінок',
        compute='_compute_cumulative_revaluation_balance',
        store=True,
        currency_field='currency_id',
        help='Net balance of confirmed revaluations: positive = surplus on 411, '
             'negative = accumulated impairment loss recognised on 975',
    )

    # --- Modernization history ---
    modernization_line_ids = fields.One2many(
        'l10n_ua.asset.modernization.line',
        'asset_id',
        string='Історія модернізацій',
    )
    modernization_count = fields.Integer(
        compute='_compute_modernization_count',
        string='Кількість модернізацій',
    )

    # --- Computed ---
    depreciation_amount = fields.Monetary(
        string='Місячна амортизація',
        compute='_compute_depreciation_amount',
        currency_field='currency_id',
        help='Місячна сума амортизації за обраним методом',
    )
    accumulated_depreciation = fields.Monetary(
        string='Накопичена амортизація',
        compute='_compute_accumulated_depreciation',
        store=True,
        currency_field='currency_id',
    )
    book_value = fields.Monetary(
        string='Залишкова вартість',
        compute='_compute_accumulated_depreciation',
        store=True,
        currency_field='currency_id',
    )

    notes = fields.Text(
        string='Примітки',
    )

    # --- Accounts for monthly depreciation posting (override group defaults) ---
    depreciation_journal_id = fields.Many2one(
        'account.journal',
        string='Журнал амортизації',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        check_company=True,
        help='Журнал для проводок амортизації. За замовч. береться з групи ОЗ.',
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат (Дт)',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Рахунок витрат на амортизацію (23/91/92/93/94). За замовч. з групи ОЗ.',
    )
    depreciation_account_id = fields.Many2one(
        'account.account',
        string='Рахунок зносу (Кт 131)',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Рахунок накопиченого зносу (131). За замовч. з групи ОЗ.',
    )

    # --- Commissioning entry (Дт 10х / Кт 152) ---
    fixed_asset_account_id = fields.Many2one(
        'account.account',
        string='Рахунок ОЗ (Дт 10х)',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Рахунок обліку ОЗ (103–109) для проводки введення в експлуатацію. '
             'За замовч. з групи ОЗ.',
    )
    commission_account_id = fields.Many2one(
        'account.account',
        string='Рахунок джерела (Кт 152/631)',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Рахунок, з якого ОЗ надходить при введенні в експлуатацію '
             '(152 «Придбання ОЗ», 631 тощо). За замовч. з групи ОЗ.',
    )
    no_commission_move = fields.Boolean(
        string='Без проводки введення',
        copy=False,
        help='Первісну вартість уже відображено іншим документом (вхідні '
             'залишки, рахунок постачальника, інвентаризація) — при введенні '
             'в експлуатацію проводка Дт 10 / Кт 152 не формується.',
    )
    commission_move_id = fields.Many2one(
        'account.move',
        string='Проводка введення',
        readonly=True,
        copy=False,
        help='Проводка введення в експлуатацію (Дт 10х / Кт 152)',
    )

    @api.onchange('group_id')
    def _onchange_group_id(self):
        if self.group_id and self.group_id.min_useful_life:
            self.useful_life = self.group_id.min_useful_life * 12
        # Inherit posting accounts from the group unless already set on the asset.
        if self.group_id:
            if not self.depreciation_journal_id:
                self.depreciation_journal_id = self.group_id.depreciation_journal_id
            if not self.expense_account_id:
                self.expense_account_id = self.group_id.expense_account_id
            if not self.depreciation_account_id:
                self.depreciation_account_id = self.group_id.depreciation_account_id
            if not self.fixed_asset_account_id:
                self.fixed_asset_account_id = self.group_id.fixed_asset_account_id
            if not self.commission_account_id:
                self.commission_account_id = self.group_id.commission_account_id

    def _get_depreciation_accounts(self):
        """Resolve (journal, expense account, accumulated-depreciation account).

        Effective value = asset field, falling back to its group's default.
        Raises if any is missing, so posting cannot create an unbalanced or
        misdirected move.
        """
        self.ensure_one()
        group = self.group_id
        journal = self.depreciation_journal_id or (group.depreciation_journal_id if group else False)
        expense = self.expense_account_id or (group.expense_account_id if group else False)
        accumulated = self.depreciation_account_id or (group.depreciation_account_id if group else False)
        missing = []
        if not journal:
            missing.append(_('журнал амортизації'))
        if not expense:
            missing.append(_('рахунок витрат (Дт)'))
        if not accumulated:
            missing.append(_('рахунок зносу (Кт 131)'))
        if missing:
            raise UserError(_(
                'Неможливо провести амортизацію ОЗ "%(asset)s": не налаштовано %(missing)s. '
                'Вкажіть на основному засобі або на групі ОЗ.',
                asset=self.display_name,
                missing=', '.join(missing),
            ))
        return journal, expense, accumulated

    def _needs_commission_move(self):
        """Whether commissioning must book the Дт 10х / Кт 152 entry."""
        self.ensure_one()
        return bool(
            self.group_id.create_commission_move
            and not self.no_commission_move
            and not self.commission_move_id
            and not self.currency_id.is_zero(self.original_value)
        )

    def _get_commission_accounts(self):
        """Resolve (journal, fixed-asset account, counterpart account).

        Same resolution as for depreciation: asset field, falling back to the
        group default; the journal is the depreciation journal.
        """
        self.ensure_one()
        group = self.group_id
        journal = self.depreciation_journal_id or group.depreciation_journal_id
        fixed = self.fixed_asset_account_id or group.fixed_asset_account_id
        counterpart = self.commission_account_id or group.commission_account_id
        missing = []
        if not journal:
            missing.append(_('журнал амортизації'))
        if not fixed:
            missing.append(_('рахунок ОЗ (Дт 10х)'))
        if not counterpart:
            missing.append(_('рахунок джерела (Кт 152/631)'))
        if missing:
            raise UserError(_(
                'Неможливо сформувати проводку введення ОЗ "%(asset)s": '
                'не налаштовано %(missing)s. Вкажіть на основному засобі або '
                'на групі ОЗ, або позначте «Без проводки введення».',
                asset=self.display_name,
                missing=', '.join(missing),
            ))
        return journal, fixed, counterpart

    def _create_commission_move(self):
        """Create and post the commissioning entry Дт 10х / Кт 152."""
        self.ensure_one()
        journal, fixed, counterpart = self._get_commission_accounts()
        ref = _('Введення в експлуатацію %(asset)s, акт %(act)s',
                asset=self.display_name, act=self.commission_act_number or '')
        amount = self.original_value
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': self.commission_date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': fixed.id,
                    'name': ref,
                    'debit': amount if amount > 0 else 0.0,
                    'credit': -amount if amount < 0 else 0.0,
                }),
                (0, 0, {
                    'account_id': counterpart.id,
                    'name': ref,
                    'debit': -amount if amount < 0 else 0.0,
                    'credit': amount if amount > 0 else 0.0,
                }),
            ],
        })
        move.action_post()
        return move

    def _remove_commission_move(self):
        """Drop the commissioning entry, like a depreciation line reset."""
        for asset in self:
            move = asset.commission_move_id
            if not move:
                continue
            asset.commission_move_id = False
            if move.state == 'posted':
                move.button_draft()
            move.unlink()

    @api.depends('revaluation_line_ids', 'revaluation_line_ids.state')
    def _compute_revaluation_count(self):
        for asset in self:
            asset.revaluation_count = len(asset.revaluation_line_ids.filtered(
                lambda l: l.state == 'confirmed'))

    @api.depends('revaluation_line_ids.revaluation_amount',
                 'revaluation_line_ids.state')
    def _compute_cumulative_revaluation_balance(self):
        for asset in self:
            asset.cumulative_revaluation_balance = sum(
                asset.revaluation_line_ids.filtered(
                    lambda l: l.state == 'confirmed'
                ).mapped('revaluation_amount')
            )

    def action_view_revaluations(self):
        self.ensure_one()
        revaluation_ids = self.revaluation_line_ids.filtered(
            lambda l: l.state == 'confirmed'
        ).mapped('revaluation_id').ids
        return {
            'name': _('Переоцінки %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.asset.revaluation',
            'view_mode': 'list,form',
            'domain': [('id', 'in', revaluation_ids)],
        }

    def action_create_revaluation(self):
        """Створити чернетку переоцінки з цим ОЗ як єдиним рядком."""
        self.ensure_one()
        if self.state not in ('open', 'paused'):
            raise UserError(_(
                'Переоцінити можна лише ОЗ у стані "В експлуатації" або "Призупинено".'
            ))
        revaluation = self.env['l10n_ua.asset.revaluation'].create({
            'date': fields.Date.context_today(self),
            'line_ids': [(0, 0, {
                'asset_id': self.id,
                'original_value_before': self.original_value,
                'accumulated_before': self.accumulated_depreciation,
                'fair_value': self.book_value,
            })],
        })
        return {
            'name': _('Переоцінка ОЗ'),
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.asset.revaluation',
            'view_mode': 'form',
            'res_id': revaluation.id,
        }

    @api.depends('modernization_line_ids', 'modernization_line_ids.state')
    def _compute_modernization_count(self):
        for asset in self:
            asset.modernization_count = len(asset.modernization_line_ids.filtered(
                lambda l: l.state == 'confirmed'))

    def action_view_modernizations(self):
        self.ensure_one()
        mod_ids = self.modernization_line_ids.mapped('modernization_id').ids
        return {
            'name': _('Модернізації %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.asset.modernization',
            'view_mode': 'list,form',
            'domain': [('id', 'in', mod_ids)],
        }

    def action_create_modernization(self):
        """Створити чернетку модернізації з цим ОЗ."""
        self.ensure_one()
        if self.state not in ('open', 'paused'):
            raise UserError(_(
                'Модернізувати можна лише ОЗ у стані "В експлуатації" або "Призупинено".'
            ))
        modernization = self.env['l10n_ua.asset.modernization'].create({
            'date': fields.Date.context_today(self),
            'line_ids': [(0, 0, {
                'asset_id': self.id,
                'original_value_before': self.original_value,
                'useful_life_before': self.useful_life,
                'amount': 0.0,
            })],
        })
        return {
            'name': _('Модернізація ОЗ'),
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.asset.modernization',
            'view_mode': 'form',
            'res_id': modernization.id,
        }

    # --- Depreciation computation ---

    @api.depends('original_value', 'salvage_value', 'useful_life',
                 'depreciation_method', 'annual_depreciation_rate',
                 'production_capacity', 'produced_units',
                 'depreciation_line_ids', 'depreciation_line_ids.state')
    def _compute_depreciation_amount(self):
        """Calculate monthly depreciation using Ukrainian methods."""
        for asset in self:
            amount = 0.0
            depreciable = asset.original_value - asset.salvage_value
            if depreciable <= 0 or not asset.useful_life:
                asset.depreciation_amount = 0
                continue

            if asset.depreciation_method == 'straight_line':
                amount = depreciable / asset.useful_life

            elif asset.depreciation_method == 'declining_balance':
                residual = depreciable
                if asset.id:
                    posted = sum(
                        asset.depreciation_line_ids.filtered(
                            lambda l: l.state == 'posted'
                        ).mapped('amount')
                    )
                    residual = max(0, depreciable - posted)
                if asset.annual_depreciation_rate:
                    annual_rate = asset.annual_depreciation_rate / 100
                else:
                    useful_years = asset.useful_life / 12
                    annual_rate = 2 / useful_years if useful_years else 0
                amount = residual * annual_rate / 12

            elif asset.depreciation_method == 'production':
                if asset.production_capacity:
                    amount = depreciable * (asset.produced_units / asset.production_capacity)
                else:
                    amount = 0

            elif asset.depreciation_method == 'cumulative':
                useful_years = asset.useful_life / 12
                if useful_years > 0:
                    months_elapsed = 0
                    if asset.id:
                        months_elapsed = len(
                            asset.depreciation_line_ids.filtered(
                                lambda l: l.state == 'posted'
                                and l.line_type == 'depreciation'))
                    current_year = int(months_elapsed / 12) + 1
                    remaining_years = max(0, useful_years - current_year + 1)
                    sum_of_years = useful_years * (useful_years + 1) / 2
                    if sum_of_years:
                        annual_amount = depreciable * remaining_years / sum_of_years
                        amount = annual_amount / 12

            asset.depreciation_amount = round(amount, 2)

    @api.depends('depreciation_line_ids', 'depreciation_line_ids.state',
                 'depreciation_line_ids.amount', 'original_value')
    def _compute_accumulated_depreciation(self):
        for asset in self:
            posted = sum(
                asset.depreciation_line_ids.filtered(
                    lambda l: l.state == 'posted'
                ).mapped('amount')
            )
            asset.accumulated_depreciation = posted
            asset.book_value = asset.original_value - posted

    def _get_depreciation_amount(self, month_number):
        """Calculate depreciation for a specific month number (1-based)."""
        self.ensure_one()
        depreciable = self.original_value - self.salvage_value
        if depreciable <= 0 or not self.useful_life:
            return 0.0

        if self.depreciation_method == 'straight_line':
            return round(depreciable / self.useful_life, 2)

        elif self.depreciation_method == 'declining_balance':
            if self.annual_depreciation_rate:
                annual_rate = self.annual_depreciation_rate / 100
            else:
                useful_years = self.useful_life / 12
                annual_rate = 2 / useful_years if useful_years else 0
            monthly_rate = annual_rate / 12
            residual = depreciable
            for _i in range(month_number - 1):
                residual -= residual * monthly_rate
                if residual <= 0:
                    return 0.0
            return round(residual * monthly_rate, 2)

        elif self.depreciation_method == 'cumulative':
            useful_years = self.useful_life / 12
            if useful_years <= 0:
                return 0.0
            current_year = int((month_number - 1) / 12) + 1
            remaining_years = max(0, useful_years - current_year + 1)
            sum_of_years = useful_years * (useful_years + 1) / 2
            if not sum_of_years:
                return 0.0
            annual_amount = depreciable * remaining_years / sum_of_years
            return round(annual_amount / 12, 2)

        elif self.depreciation_method == 'production':
            if self.production_capacity:
                return round(
                    depreciable * (self.produced_units / self.production_capacity), 2
                )
            return 0.0

        return 0.0

    # --- State actions ---

    def action_commission(self):
        """Commission asset — put into operation."""
        for asset in self:
            vals = {'state': 'open'}
            if not asset.commission_date:
                vals['commission_date'] = fields.Date.context_today(self)
            if not asset.commission_act_number:
                vals['commission_act_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.asset.commission.act'
                ) or _('New')
            asset.write(vals)
            if asset._needs_commission_move():
                asset.commission_move_id = asset._create_commission_move()

    def action_pause(self):
        """Pause depreciation."""
        self.write({'state': 'paused'})

    def action_resume(self):
        """Resume from paused state."""
        self.write({'state': 'open'})

    def action_write_off(self):
        """Write off asset."""
        for asset in self:
            vals = {'state': 'close'}
            if not asset.writeoff_date:
                vals['writeoff_date'] = fields.Date.context_today(self)
            if not asset.writeoff_act_number:
                vals['writeoff_act_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.asset.writeoff.act'
                ) or _('New')
            asset.write(vals)

    def action_draft(self):
        """Return to draft."""
        for asset in self:
            if asset.revaluation_line_ids.filtered(lambda l: l.state == 'confirmed'):
                raise UserError(_(
                    'Не можна повернути ОЗ "%s" в чернетку: існують підтверджені переоцінки. '
                    'Спочатку скасуйте документи переоцінки.'
                ) % asset.display_name)
        self._remove_commission_move()
        self.write({
            'state': 'draft',
            'commission_date': False,
            'commission_act_number': False,
            'writeoff_date': False,
            'writeoff_act_number': False,
            'writeoff_reason': False,
        })

    def action_compute_depreciation(self):
        """Compute depreciation board for the useful life period.

        After a posted revaluation, the remaining schedule is computed
        against the current residual (book_value - salvage_value) spread
        over the remaining months — П(С)БО 7 п.17 prescribes restating
        amortization from the post-revaluation balance.
        """
        DepLine = self.env['l10n_ua.asset.depreciation']
        for asset in self:
            if not asset.useful_life or not asset.original_value:
                raise UserError(_('Вкажіть первісну вартість та строк корисного використання.'))
            # Remove draft lines
            asset.depreciation_line_ids.filtered(lambda l: l.state == 'draft').unlink()
            # Determine start date
            start_date = asset.commission_date or asset.acquisition_date
            if not start_date:
                raise UserError(_('Вкажіть дату придбання або введення в експлуатацію.'))
            # Count posted depreciation rows only (not revaluation adjustments)
            posted_count = len(asset.depreciation_line_ids.filtered(
                lambda l: l.state == 'posted' and l.line_type == 'depreciation'))
            accumulated = sum(asset.depreciation_line_ids.filtered(
                lambda l: l.state == 'posted').mapped('amount'))
            has_revaluation = any(
                l.state == 'posted' and l.line_type == 'revaluation'
                for l in asset.depreciation_line_ids
            )
            depreciable = asset.original_value - asset.salvage_value
            remaining_months = max(0, asset.useful_life - posted_count)

            # Post-revaluation: recompute from current residual.
            # initial_residual is the depreciable portion of book_value at
            # the start of the remaining schedule; fixed for the run so
            # straight-line and cumulative formulas use the snapshot, while
            # declining-balance decays its own running_residual each month.
            if has_revaluation:
                current_book = asset.original_value - accumulated
                initial_residual = max(0, current_book - asset.salvage_value)
            else:
                initial_residual = max(0, depreciable - accumulated)
            running_residual = initial_residual

            # П(С)БО 7 п.29: depreciation starts in the month following the
            # commissioning month. Rows are dated at the end of their month.
            # A board that already has posted rows continues right after the
            # last of them (keeps legacy boards without a gap).
            posted_dates = asset.depreciation_line_ids.filtered(
                lambda l: l.state == 'posted' and l.line_type == 'depreciation'
            ).mapped('date')
            if posted_dates:
                anchor_date, anchor_offset = max(posted_dates), posted_count
            else:
                anchor_date, anchor_offset = start_date, 0

            for month_num in range(posted_count + 1, asset.useful_life + 1):
                month_in_remaining = month_num - posted_count
                amount = asset._get_future_amount(
                    method=asset.depreciation_method,
                    month_in_remaining=month_in_remaining,
                    remaining_months=remaining_months,
                    initial_residual=initial_residual,
                    running_residual=running_residual,
                )
                # Cap by what's left to depreciate
                if amount > running_residual:
                    amount = max(0, running_residual)
                if amount <= 0:
                    break
                accumulated += amount
                running_residual = max(0, running_residual - amount)
                line_date = date_utils.end_of(
                    anchor_date + relativedelta(months=month_num - anchor_offset),
                    'month')

                DepLine.create({
                    'asset_id': asset.id,
                    'date': line_date,
                    'amount': amount,
                    'accumulated': accumulated,
                    'remaining': asset.original_value - accumulated,
                    'state': 'draft',
                })

    def _get_future_amount(self, method, month_in_remaining,
                           remaining_months, initial_residual, running_residual):
        """Compute one month of depreciation given the remaining state.

        Stateful version of _get_depreciation_amount: works correctly
        whether or not a revaluation has happened. month_in_remaining is
        1-based relative to the START of the remaining schedule (the
        first month being generated by the current run). initial_residual
        is the depreciable amount at the start of the remaining schedule;
        running_residual is what is left after this run's prior months.
        """
        self.ensure_one()
        if initial_residual <= 0 or remaining_months <= 0:
            return 0.0
        if method == 'straight_line':
            return round(initial_residual / remaining_months, 2)
        elif method == 'declining_balance':
            if self.annual_depreciation_rate:
                monthly_rate = self.annual_depreciation_rate / 100 / 12
            else:
                useful_years = self.useful_life / 12
                monthly_rate = (2 / useful_years / 12) if useful_years else 0
            return round(running_residual * monthly_rate, 2)
        elif method == 'cumulative':
            remaining_years = max(1, remaining_months / 12)
            year_in_remaining = int((month_in_remaining - 1) / 12) + 1
            years_left = max(0, remaining_years - year_in_remaining + 1)
            sum_of_years = remaining_years * (remaining_years + 1) / 2
            if not sum_of_years:
                return 0.0
            annual = initial_residual * years_left / sum_of_years
            return round(annual / 12, 2)
        elif method == 'production':
            if self.production_capacity:
                return round(
                    initial_residual * (self.produced_units / self.production_capacity), 2
                )
            return 0.0
        return 0.0

    # --- Print actions ---

    def action_print_oz6(self):
        """Print OZ-6 Inventory Card."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_asset_oz6'
        ).report_action(self)

    def action_print_commission_act(self):
        """Print Commissioning Act."""
        self.ensure_one()
        if not self.commission_act_number:
            self.action_commission()
        return self.env.ref(
            'l10n_ua_assets.action_report_asset_commission'
        ).report_action(self)

    def action_print_writeoff_act(self):
        """Print Write-off Act."""
        self.ensure_one()
        if not self.writeoff_act_number:
            self.action_write_off()
        return self.env.ref(
            'l10n_ua_assets.action_report_asset_writeoff'
        ).report_action(self)

    # --- Helpers for reports ---

    def _get_depreciation_method_name(self):
        """Return Ukrainian name of depreciation method."""
        self.ensure_one()
        method_map = {
            'straight_line': 'Прямолінійний',
            'declining_balance': 'Зменшення залишкової вартості',
            'production': 'Виробничий',
            'cumulative': 'Кумулятивний',
        }
        return method_map.get(self.depreciation_method, '')

    def _get_group_name(self):
        """Return asset group display string."""
        self.ensure_one()
        if self.group_id:
            return '%s — %s' % (self.group_id.code, self.group_id.name)
        return ''


class L10nUaAssetDepreciation(models.Model):
    _name = 'l10n_ua.asset.depreciation'
    _description = 'Амортизаційне нарахування'
    _order = 'date, id'

    asset_id = fields.Many2one(
        'l10n_ua.asset',
        string='Основний засіб',
        required=True,
        ondelete='cascade',
    )
    date = fields.Date(
        string='Дата',
        required=True,
    )
    amount = fields.Monetary(
        string='Амортизація за період',
        currency_field='currency_id',
    )
    accumulated = fields.Monetary(
        string='Накопичена амортизація',
        currency_field='currency_id',
    )
    remaining = fields.Monetary(
        string='Залишкова вартість',
        currency_field='currency_id',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('posted', 'Проведено'),
        ],
        string='Стан',
        default='draft',
    )
    line_type = fields.Selection(
        selection=[
            ('depreciation', 'Амортизація'),
            ('revaluation', 'Переоцінка'),
        ],
        string='Тип рядка',
        default='depreciation',
        required=True,
    )
    revaluation_id = fields.Many2one(
        'l10n_ua.asset.revaluation',
        string='Документ переоцінки',
        ondelete='set null',
        readonly=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Проводка',
        readonly=True,
        copy=False,
        help='Бухгалтерська проводка амортизації (Дт витрати / Кт 131)',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='asset_id.currency_id',
    )

    def action_post(self):
        """Post depreciation line and book it to the general ledger.

        Дт expense account (23/91/92/93/94) — Кт 131 «Знос ОЗ».
        Revaluation adjustment lines carry no cash impact of their own here —
        their move is created by the revaluation document — so only genuine
        depreciation rows generate a move.
        """
        for line in self:
            if line.state == 'posted':
                continue
            if line.line_type == 'depreciation' and line.amount and not line.move_id:
                line.move_id = line._create_depreciation_move()
            line.state = 'posted'

    def action_draft(self):
        """Revert to draft, removing the depreciation move if any."""
        for line in self:
            move = line.move_id
            if move:
                line.move_id = False
                if move.state == 'posted':
                    move.button_draft()
                move.unlink()
            line.state = 'draft'

    def _create_depreciation_move(self):
        """Create and post the monthly depreciation journal entry."""
        self.ensure_one()
        asset = self.asset_id
        journal, expense, accumulated = asset._get_depreciation_accounts()
        ref = _('Амортизація %(asset)s за %(date)s',
                asset=asset.display_name, date=self.date)
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': self.date,
            'ref': ref,
            'company_id': asset.company_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': expense.id,
                    'name': ref,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': accumulated.id,
                    'name': ref,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        })
        move.action_post()
        return move

    def unlink(self):
        if not self.env.context.get('skip_revaluation_protection'):
            protected = self.filtered(
                lambda l: l.line_type == 'revaluation' and l.revaluation_id
                and l.revaluation_id.state == 'confirmed'
            )
            if protected:
                raise UserError(_(
                    'Не можна видалити коригувальний рядок переоцінки. '
                    'Спочатку скасуйте документ переоцінки.'
                ))
        return super().unlink()

    def write(self, vals):
        if vals and any(self.mapped(lambda l: l.line_type == 'revaluation'
                                    and l.revaluation_id
                                    and l.revaluation_id.state == 'confirmed')):
            allowed = {'state'}
            forbidden = set(vals) - allowed
            if forbidden:
                raise UserError(_(
                    'Не можна редагувати поля %s коригувального рядка переоцінки. '
                    'Спочатку скасуйте документ переоцінки.'
                ) % ', '.join(forbidden))
        return super().write(vals)
