"""Переоцінка ОЗ — згідно П(С)БО 7, п. 16-21."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class L10nUaAssetRevaluation(models.Model):
    _name = 'l10n_ua.asset.revaluation'
    _description = 'Переоцінка основних засобів'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Номер',
        default=lambda self: _('Нова'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    date = fields.Date(
        string='Дата переоцінки',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('confirmed', 'Підтверджено'),
            ('cancelled', 'Скасовано'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
        copy=False,
    )

    note = fields.Text(string='Примітки')

    group_id = fields.Many2one(
        'l10n_ua.asset.group',
        string='Група ОЗ',
        help='Опціональний фільтр: переоцінювати тільки ОЗ цієї групи',
    )

    line_ids = fields.One2many(
        'l10n_ua.asset.revaluation.line',
        'revaluation_id',
        string='Рядки переоцінки',
        copy=True,
    )

    # --- Бухгалтерія ---
    journal_id = fields.Many2one(
        'account.journal',
        string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help='Бухгалтерський журнал для проводок переоцінки',
        check_company=True,
    )
    fixed_asset_account_id = fields.Many2one(
        'account.account',
        string='Рахунок ОЗ (10)',
        domain="[('company_ids', 'in', company_id)]",
        help='Рахунок первісної вартості ОЗ (за замовч. 10)',
        check_company=True,
    )
    accumulated_depreciation_account_id = fields.Many2one(
        'account.account',
        string='Рахунок зносу (131)',
        domain="[('company_ids', 'in', company_id)]",
        help='Рахунок накопиченого зносу (за замовч. 131)',
        check_company=True,
    )
    revaluation_surplus_account_id = fields.Many2one(
        'account.account',
        string='Дооцінка (411)',
        domain="[('company_ids', 'in', company_id)]",
        help='Капітал у дооцінках (за замовч. 411)',
        check_company=True,
    )
    impairment_loss_account_id = fields.Many2one(
        'account.account',
        string='Уцінка (975)',
        domain="[('company_ids', 'in', company_id)]",
        help='Витрати на уцінку ОЗ (за замовч. 975)',
        check_company=True,
    )
    other_income_account_id = fields.Many2one(
        'account.account',
        string='Доход від відновлення (746)',
        domain="[('company_ids', 'in', company_id)]",
        help='Інші операційні доходи — використовується при дооцінці '
             'після попередньої уцінки (П(С)БО 7 п.20)',
        check_company=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
        check_company=True,
    )

    # --- Підсумки ---
    total_original_change = fields.Monetary(
        string='Зміна первісної вартості',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_accumulated_change = fields.Monetary(
        string='Зміна накопиченого зносу',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_net_change = fields.Monetary(
        string='Чиста сума переоцінки',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Загальна сума дооцінки (+) або уцінки (-)',
    )

    # --- Компанія / валюта ---
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

    @api.depends('line_ids.original_change', 'line_ids.accumulated_change',
                 'line_ids.revaluation_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_original_change = sum(rec.line_ids.mapped('original_change'))
            rec.total_accumulated_change = sum(rec.line_ids.mapped('accumulated_change'))
            rec.total_net_change = sum(rec.line_ids.mapped('revaluation_amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Нова'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.asset.revaluation'
                ) or _('Нова')
        return super().create(vals_list)

    # --- Дії ---

    def action_confirm(self):
        """Підтвердити переоцінку: створити коригувальні рядки амортизації,
        оновити первісну вартість ОЗ, створити account.move.

        Бере row-level lock на документ, щоб уникнути race-condition
        при double-click або паралельних викликах.
        """
        # Acquire FOR UPDATE on this revaluation row so a concurrent
        # confirm call serialises behind us instead of producing
        # duplicate moves / adjustment rows.
        if self.ids:
            self.env.cr.execute(
                'SELECT id FROM l10n_ua_asset_revaluation '
                'WHERE id IN %s FOR UPDATE',
                (tuple(self.ids),),
            )
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Переоцінку можна підтвердити лише з чернетки.'))
            if not rec.line_ids:
                raise UserError(_('Додайте хоча б один ОЗ до переоцінки.'))
            # Server-side check that all referenced assets are still in
            # an operable state — the form-level domain is only a UI hint.
            bad_assets = rec.line_ids.filtered(
                lambda l: l.asset_id.state not in ('open', 'paused')
            ).mapped('asset_id')
            if bad_assets:
                raise UserError(_(
                    'Не можна переоцінити ОЗ у стані відмінному від '
                    '«В експлуатації» або «Призупинено»: %s'
                ) % ', '.join(bad_assets.mapped('display_name')))
            # Refresh snapshot from live values to avoid drift when
            # depreciation was posted between draft creation and confirm.
            rec.line_ids._refresh_snapshot()
            rec._validate_accounts()
            rec.line_ids._apply_to_assets()
            rec._create_account_move()
            rec.state = 'confirmed'
        return True

    def action_cancel(self):
        """Скасувати переоцінку: спершу скасувати проводку, потім
        повернути активам попередні значення, видалити коригувальні
        рядки амортизації.

        Move cancel/draft може впасти (закритий період, узгоджені
        рядки) — тому робимо це ПЕРЕД мутацією активів, щоб не
        залишити неузгоджений стан.
        """
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Скасувати можна лише підтверджену переоцінку.'))
            if rec.move_id:
                if rec.move_id.state == 'posted':
                    rec.move_id.button_draft()
                rec.move_id.button_cancel()
            rec.line_ids._revert_from_assets()
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        """Повернути в чернетку (тільки якщо скасовано)."""
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('У чернетку можна повернути лише скасовану переоцінку.'))
            rec.state = 'draft'
        return True

    def action_print(self):
        """Друк акту переоцінки."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_asset_revaluation'
        ).report_action(self)

    def action_view_move(self):
        """Відкрити пов'язану бухгалтерську проводку."""
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            'name': _('Проводка переоцінки'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _validate_accounts(self):
        """Перевірити, що всі необхідні рахунки/журнал задані.

        Account 746 (other_income_account_id) is required only when a
        дооцінка line offsets a prior уцінка on the same asset.
        """
        self.ensure_one()
        missing = []
        if not self.journal_id:
            missing.append(_('Журнал'))
        if not self.fixed_asset_account_id:
            missing.append(_('Рахунок ОЗ (10)'))
        if not self.accumulated_depreciation_account_id:
            missing.append(_('Рахунок зносу (131)'))
        needs_411 = needs_975 = needs_746 = False
        for line in self.line_ids:
            prior = line.asset_id.cumulative_revaluation_balance
            amount = line.revaluation_amount
            if amount > 0:
                recovery = min(max(0, -prior), amount)
                surplus = amount - recovery
                if recovery > 0:
                    needs_746 = True
                if surplus > 0:
                    needs_411 = True
            elif amount < 0:
                offset = min(max(0, prior), -amount)
                loss = -amount - offset
                if offset > 0:
                    needs_411 = True
                if loss > 0:
                    needs_975 = True
        if needs_411 and not self.revaluation_surplus_account_id:
            missing.append(_('Рахунок дооцінки (411)'))
        if needs_975 and not self.impairment_loss_account_id:
            missing.append(_('Рахунок уцінки (975)'))
        if needs_746 and not self.other_income_account_id:
            missing.append(_('Рахунок інших доходів (746)'))
        if missing:
            raise UserError(_(
                'Не заповнено обов\'язкові поля: %s'
            ) % ', '.join(missing))

    def _create_account_move(self):
        """Створити проводку для переоцінки (П(С)БО 7 п.16-21, Інструкція №291).

        Asset-side legs (rebalancing 10 / 131) are always posted:
            ΔOriginal > 0:  Дт 10
            ΔOriginal < 0:  Кт 10
            ΔAccum    > 0:  Кт 131
            ΔAccum    < 0:  Дт 131

        Net effect (Δbook = revaluation_amount) is split using the asset's
        cumulative_revaluation_balance (П(С)БО 7 п.20-21):
          Дооцінка (Δbook > 0):
            Recovery of prior уцінка (up to |prior loss|): Кт 746
            Excess (creates surplus):                       Кт 411
          Уцінка (Δbook < 0):
            Offset of prior surplus (up to prior surplus):  Дт 411
            Excess (creates loss):                          Дт 975
        """
        self.ensure_one()
        move_lines = []
        ref = _('Переоцінка ОЗ %s від %s') % (self.name, self.date)

        for line in self.line_ids:
            asset = line.asset_id
            prior = asset.cumulative_revaluation_balance
            move_lines += self._build_move_lines_for_line(line, prior)

        if not move_lines:
            return

        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.move_id = move

    def _build_move_lines_for_line(self, line, prior_balance):
        """Build the (0,0,vals) tuples for one revaluation line.

        Splits ΔOriginal/ΔAccum (asset rebalancing) from the net Δbook
        allocation across 411/746/975 per П(С)БО 7 п.20-21.
        """
        self.ensure_one()
        asset_name = line.asset_id.name
        d_orig = line.original_change
        d_accum = line.accumulated_change
        d_book = line.revaluation_amount
        result = []

        # Asset-side rebalancing on 10
        if d_orig > 0:
            result.append(self._mk_line(self.fixed_asset_account_id,
                                        _('Переоцінка первісної: %s') % asset_name,
                                        debit=d_orig))
        elif d_orig < 0:
            result.append(self._mk_line(self.fixed_asset_account_id,
                                        _('Переоцінка первісної: %s') % asset_name,
                                        credit=-d_orig))

        # Asset-side rebalancing on 131
        if d_accum > 0:
            result.append(self._mk_line(self.accumulated_depreciation_account_id,
                                        _('Переоцінка зносу: %s') % asset_name,
                                        credit=d_accum))
        elif d_accum < 0:
            result.append(self._mk_line(self.accumulated_depreciation_account_id,
                                        _('Переоцінка зносу: %s') % asset_name,
                                        debit=-d_accum))

        # Net Δbook allocation (П(С)БО 7 п.20-21)
        if d_book > 0:
            recovery = min(max(0, -prior_balance), d_book)
            surplus = d_book - recovery
            if recovery > 0:
                result.append(self._mk_line(
                    self.other_income_account_id,
                    _('Відновлення вартості (746): %s') % asset_name,
                    credit=recovery))
            if surplus > 0:
                result.append(self._mk_line(
                    self.revaluation_surplus_account_id,
                    _('Дооцінка (411): %s') % asset_name,
                    credit=surplus))
        elif d_book < 0:
            offset = min(max(0, prior_balance), -d_book)
            loss = -d_book - offset
            if offset > 0:
                result.append(self._mk_line(
                    self.revaluation_surplus_account_id,
                    _('Списання дооцінки (411): %s') % asset_name,
                    debit=offset))
            if loss > 0:
                result.append(self._mk_line(
                    self.impairment_loss_account_id,
                    _('Уцінка (975): %s') % asset_name,
                    debit=loss))
        return result

    @staticmethod
    def _mk_line(account, name, debit=0.0, credit=0.0):
        return (0, 0, {
            'account_id': account.id,
            'name': name,
            'debit': debit,
            'credit': credit,
        })

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_(
                    'Не можна видалити підтверджену переоцінку. Спочатку скасуйте її.'
                ))
        return super().unlink()


class L10nUaAssetRevaluationLine(models.Model):
    _name = 'l10n_ua.asset.revaluation.line'
    _description = 'Рядок переоцінки ОЗ'
    _order = 'revaluation_id, id'
    _check_company_auto = True

    revaluation_id = fields.Many2one(
        'l10n_ua.asset.revaluation',
        string='Переоцінка',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='revaluation_id.company_id',
        store=True,
    )
    asset_id = fields.Many2one(
        'l10n_ua.asset',
        string='Основний засіб',
        required=True,
        domain="[('state', 'in', ['open', 'paused']),"
               " ('company_id', '=?', company_id)]",
        check_company=True,
    )

    # Снапшот «до» (заморожується при створенні рядка)
    original_value_before = fields.Monetary(
        string='Первісна до',
        currency_field='currency_id',
    )
    accumulated_before = fields.Monetary(
        string='Знос до',
        currency_field='currency_id',
    )
    book_value_before = fields.Monetary(
        string='Залишкова до',
        compute='_compute_book_value_before',
        store=True,
        currency_field='currency_id',
    )

    # Введення користувача
    fair_value = fields.Monetary(
        string='Справедлива вартість',
        currency_field='currency_id',
        required=True,
        help='Нова залишкова (справедлива) вартість ОЗ',
    )

    # Обчислені «після»
    revaluation_index = fields.Float(
        string='Індекс переоцінки',
        compute='_compute_revaluation',
        store=True,
        digits=(12, 6),
        help='fair_value / book_value_before',
    )
    original_value_after = fields.Monetary(
        string='Первісна після',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
    )
    accumulated_after = fields.Monetary(
        string='Знос після',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
    )
    book_value_after = fields.Monetary(
        string='Залишкова після',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
    )

    original_change = fields.Monetary(
        string='Δ Первісної',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
    )
    accumulated_change = fields.Monetary(
        string='Δ Зносу',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
    )
    revaluation_amount = fields.Monetary(
        string='Сума переоцінки',
        compute='_compute_revaluation',
        store=True,
        currency_field='currency_id',
        help='book_value_after - book_value_before',
    )

    revaluation_type = fields.Selection(
        selection=[
            ('increase', 'Дооцінка'),
            ('decrease', 'Уцінка'),
            ('none', 'Без зміни'),
        ],
        string='Тип',
        compute='_compute_revaluation',
        store=True,
    )

    state = fields.Selection(
        related='revaluation_id.state',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='revaluation_id.currency_id',
    )

    @api.onchange('asset_id')
    def _onchange_asset_id(self):
        """Захопити поточні значення ОЗ як снапшот «до»."""
        if self.asset_id:
            self.original_value_before = self.asset_id.original_value
            self.accumulated_before = self.asset_id.accumulated_depreciation
            if not self.fair_value:
                self.fair_value = self.asset_id.book_value

    @api.depends('original_value_before', 'accumulated_before')
    def _compute_book_value_before(self):
        for line in self:
            line.book_value_before = line.original_value_before - line.accumulated_before

    @api.depends('book_value_before', 'fair_value',
                 'original_value_before', 'accumulated_before')
    def _compute_revaluation(self):
        for line in self:
            currency = line.currency_id or line.revaluation_id.currency_id
            book_before = line.book_value_before
            # Use currency.is_zero rather than raw `> 0` so a tiny rounding
            # residue (e.g. 0.001) can't survive the guard and blow up index.
            if currency and not currency.is_zero(book_before) and book_before > 0:
                index = line.fair_value / book_before
            else:
                index = 0.0
            line.revaluation_index = round(index, 6)
            if currency:
                line.original_value_after = currency.round(
                    line.original_value_before * index)
                line.accumulated_after = currency.round(
                    line.accumulated_before * index)
            else:
                line.original_value_after = round(
                    line.original_value_before * index, 2)
                line.accumulated_after = round(
                    line.accumulated_before * index, 2)
            line.book_value_after = line.original_value_after - line.accumulated_after
            line.original_change = line.original_value_after - line.original_value_before
            line.accumulated_change = line.accumulated_after - line.accumulated_before
            line.revaluation_amount = line.book_value_after - book_before

            if currency and currency.is_zero(line.revaluation_amount):
                line.revaluation_type = 'none'
            elif line.revaluation_amount > 0:
                line.revaluation_type = 'increase'
            else:
                line.revaluation_type = 'decrease'

    @api.constrains('fair_value', 'book_value_before')
    def _check_fair_value(self):
        for line in self:
            currency = line.currency_id or line.revaluation_id.currency_id
            if line.fair_value < 0:
                raise ValidationError(_(
                    'Справедлива вартість не може бути від\'ємною.'
                ))
            # Use currency.compare_amounts so a tiny rounding tail
            # (0.001) doesn't masquerade as positive book value.
            if currency and currency.compare_amounts(line.book_value_before, 0) <= 0:
                raise ValidationError(_(
                    'Залишкова вартість ОЗ "%s" повинна бути більше нуля для переоцінки.'
                ) % line.asset_id.display_name)

    def _refresh_snapshot(self):
        """Оновити снапшот original_value_before / accumulated_before з
        поточних значень асета. Викликається в action_confirm щоб уникнути
        drift коли амортизація постилась між draft-creation і confirm.

        Зберігається fair_value (вже введена користувачем) — індекс
        і всі after-поля перерахуються через api.depends.
        """
        for line in self:
            asset = line.asset_id
            if not asset:
                continue
            updates = {}
            if line.original_value_before != asset.original_value:
                updates['original_value_before'] = asset.original_value
            if line.accumulated_before != asset.accumulated_depreciation:
                updates['accumulated_before'] = asset.accumulated_depreciation
            if updates:
                line.write(updates)

    def _apply_to_assets(self):
        """Застосувати переоцінку до ОЗ: створити коригувальний рядок амортизації
        та оновити первісну вартість.
        """
        DepLine = self.env['l10n_ua.asset.depreciation']
        for line in self:
            asset = line.asset_id
            # Коригувальний рядок амортизації (зі станом posted)
            new_accumulated = asset.accumulated_depreciation + line.accumulated_change
            new_book = line.original_value_after - new_accumulated
            DepLine.create({
                'asset_id': asset.id,
                'date': line.revaluation_id.date,
                'amount': line.accumulated_change,
                'accumulated': new_accumulated,
                'remaining': new_book,
                'state': 'posted',
                'line_type': 'revaluation',
                'revaluation_id': line.revaluation_id.id,
            })
            # Оновити первісну вартість
            asset.write({'original_value': line.original_value_after})

    def _revert_from_assets(self):
        """Відкотити переоцінку — видалити коригувальні рядки амортизації
        та повернути первісну вартість.

        Блокується якщо після цієї переоцінки на актив було проведено
        амортизацію або підтверджено пізнішу переоцінку.
        """
        Depreciation = self.env['l10n_ua.asset.depreciation']
        for line in self:
            asset = line.asset_id
            rev_date = line.revaluation_id.date
            # Check (a): no posted depreciation after revaluation date
            later_dep = Depreciation.search([
                ('asset_id', '=', asset.id),
                ('revaluation_id', '=', False),
                ('line_type', '=', 'depreciation'),
                ('state', '=', 'posted'),
                ('date', '>', rev_date),
            ], limit=1)
            if later_dep:
                raise UserError(_(
                    'Не можна скасувати переоцінку %s: на ОЗ "%s" '
                    'після дати %s вже проведено амортизацію (%s).'
                ) % (
                    line.revaluation_id.name,
                    asset.display_name,
                    rev_date,
                    later_dep.date,
                ))
            # Check (b): no later confirmed revaluations on the same asset
            later_rev = self.env['l10n_ua.asset.revaluation.line'].search([
                ('asset_id', '=', asset.id),
                ('state', '=', 'confirmed'),
                ('revaluation_id.date', '>', rev_date),
                ('id', '!=', line.id),
            ], limit=1)
            if later_rev:
                raise UserError(_(
                    'Не можна скасувати переоцінку %s: на ОЗ "%s" '
                    'після цього було підтверджено переоцінку %s від %s. '
                    'Спочатку скасуйте її.'
                ) % (
                    line.revaluation_id.name,
                    asset.display_name,
                    later_rev.revaluation_id.name,
                    later_rev.revaluation_id.date,
                ))
            adj = Depreciation.search([
                ('asset_id', '=', asset.id),
                ('revaluation_id', '=', line.revaluation_id.id),
                ('line_type', '=', 'revaluation'),
            ])
            adj.with_context(skip_revaluation_protection=True).unlink()
            asset.write({'original_value': line.original_value_before})
