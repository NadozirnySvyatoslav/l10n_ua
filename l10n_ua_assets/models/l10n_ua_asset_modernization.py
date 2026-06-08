"""Модернізація / реконструкція ОЗ — П(С)БО 7 п.14."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class L10nUaAssetModernization(models.Model):
    _name = 'l10n_ua.asset.modernization'
    _description = 'Модернізація основних засобів'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Номер',
        default=lambda self: _('Нова'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    date = fields.Date(
        string='Дата',
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

    document_reference = fields.Char(
        string='Документ-підстава',
        help='№ та дата договору / акту прийому робіт',
    )
    description = fields.Text(string='Опис робіт')

    line_ids = fields.One2many(
        'l10n_ua.asset.modernization.line',
        'modernization_id',
        string='Рядки модернізації',
        copy=True,
    )

    # --- Бухгалтерія ---
    journal_id = fields.Many2one(
        'account.journal',
        string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )
    fixed_asset_account_id = fields.Many2one(
        'account.account',
        string='Рахунок ОЗ (10)',
        domain="[('company_ids', 'in', company_id)]",
    )
    source_account_id = fields.Many2one(
        'account.account',
        string='Рахунок джерела (152/631)',
        domain="[('company_ids', 'in', company_id)]",
        help='Рахунок капітальних інвестицій (152) або розрахунків з '
             'постачальниками (631), з якого переноситься сума модернізації',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
    )

    # --- Підсумки ---
    total_amount = fields.Monetary(
        string='Загальна сума',
        compute='_compute_total_amount',
        store=True,
        currency_field='currency_id',
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

    @api.depends('line_ids.amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Нова'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.asset.modernization'
                ) or _('Нова')
        return super().create(vals_list)

    # --- Дії ---

    def action_confirm(self):
        """Підтвердити модернізацію: збільшити первісну вартість і
        (опціонально) строк корисного використання ОЗ, створити проводку.
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Модернізацію можна підтвердити лише з чернетки.'))
            if not rec.line_ids:
                raise UserError(_('Додайте хоча б один ОЗ до модернізації.'))
            zero_amount = rec.line_ids.filtered(lambda l: l.amount <= 0)
            if zero_amount:
                raise UserError(_(
                    'Заповніть суму модернізації для всіх рядків.'
                ))
            rec._validate_accounts()
            rec.line_ids._apply_to_assets()
            rec._create_account_move()
            rec.state = 'confirmed'
        return True

    def action_cancel(self):
        """Скасувати модернізацію: повернути активам попередні значення,
        скасувати account.move.
        """
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Скасувати можна лише підтверджену модернізацію.'))
            if rec.move_id:
                if rec.move_id.state == 'posted':
                    rec.move_id.button_draft()
                rec.move_id.button_cancel()
            rec.line_ids._revert_from_assets()
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('У чернетку можна повернути лише скасовану.'))
            rec.state = 'draft'
        return True

    def action_print(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_asset_modernization'
        ).report_action(self)

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            'name': _('Проводка модернізації'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _validate_accounts(self):
        self.ensure_one()
        missing = []
        if not self.journal_id:
            missing.append(_('Журнал'))
        if not self.fixed_asset_account_id:
            missing.append(_('Рахунок ОЗ (10)'))
        if not self.source_account_id:
            missing.append(_('Рахунок джерела'))
        if missing:
            raise UserError(_(
                'Не заповнено обов\'язкові поля: %s'
            ) % ', '.join(missing))

    def _create_account_move(self):
        """Створити проводку модернізації: Дт 10 / Кт 152 (або 631)."""
        self.ensure_one()
        move_lines = []
        ref = _('Модернізація ОЗ %s від %s') % (self.name, self.date)

        for line in self.line_ids:
            if not line.amount:
                continue
            name = _('Модернізація: %s') % line.asset_id.name
            move_lines.append((0, 0, {
                'account_id': self.fixed_asset_account_id.id,
                'name': name,
                'debit': line.amount,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'account_id': self.source_account_id.id,
                'name': name,
                'debit': 0.0,
                'credit': line.amount,
            }))
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

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_(
                    'Не можна видалити підтверджену модернізацію. Спочатку скасуйте її.'
                ))
        return super().unlink()


class L10nUaAssetModernizationLine(models.Model):
    _name = 'l10n_ua.asset.modernization.line'
    _description = 'Рядок модернізації ОЗ'
    _order = 'modernization_id, id'

    modernization_id = fields.Many2one(
        'l10n_ua.asset.modernization',
        string='Модернізація',
        required=True,
        ondelete='cascade',
    )
    asset_id = fields.Many2one(
        'l10n_ua.asset',
        string='Основний засіб',
        required=True,
        domain="[('state', 'in', ['open', 'paused'])]",
    )
    work_description = fields.Char(
        string='Опис робіт',
        help='Конкретні роботи з модернізації цього ОЗ',
    )
    amount = fields.Monetary(
        string='Сума модернізації',
        required=True,
        currency_field='currency_id',
        help='На скільки збільшується первісна вартість',
    )
    useful_life_extension = fields.Integer(
        string='+ Строк (міс.)',
        default=0,
        help='На скільки місяців подовжується строк корисного використання',
    )

    # Snapshot before
    original_value_before = fields.Monetary(
        string='Первісна до',
        currency_field='currency_id',
    )
    useful_life_before = fields.Integer(string='Строк до (міс.)')

    # Computed after
    original_value_after = fields.Monetary(
        string='Первісна після',
        compute='_compute_after',
        store=True,
        currency_field='currency_id',
    )
    useful_life_after = fields.Integer(
        string='Строк після (міс.)',
        compute='_compute_after',
        store=True,
    )

    state = fields.Selection(
        related='modernization_id.state',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='modernization_id.currency_id',
    )

    @api.onchange('asset_id')
    def _onchange_asset_id(self):
        if self.asset_id:
            self.original_value_before = self.asset_id.original_value
            self.useful_life_before = self.asset_id.useful_life

    @api.depends('original_value_before', 'amount',
                 'useful_life_before', 'useful_life_extension')
    def _compute_after(self):
        for line in self:
            line.original_value_after = line.original_value_before + line.amount
            line.useful_life_after = line.useful_life_before + line.useful_life_extension

    @api.constrains('amount', 'state')
    def _check_amount(self):
        for line in self:
            if line.state != 'draft' and line.amount <= 0:
                raise ValidationError(_(
                    'Сума модернізації повинна бути більше нуля.'
                ))

    @api.constrains('useful_life_extension')
    def _check_useful_life_extension(self):
        for line in self:
            if line.useful_life_extension < 0:
                raise ValidationError(_(
                    'Подовження строку не може бути від\'ємним.'
                ))

    def _apply_to_assets(self):
        """Збільшити original_value і useful_life ОЗ."""
        for line in self:
            asset = line.asset_id
            vals = {'original_value': line.original_value_after}
            if line.useful_life_extension:
                vals['useful_life'] = line.useful_life_after
            asset.write(vals)

    def _revert_from_assets(self):
        """Повернути original_value і useful_life ОЗ.

        Блокується якщо після цієї модернізації на актив було проведено
        амортизацію або підтверджено пізнішу модернізацію.
        """
        Depreciation = self.env['l10n_ua.asset.depreciation']
        for line in self:
            asset = line.asset_id
            mod_date = line.modernization_id.date
            # Check (a): no posted depreciation after modernization date
            later_dep = Depreciation.search([
                ('asset_id', '=', asset.id),
                ('state', '=', 'posted'),
                ('date', '>', mod_date),
            ], limit=1)
            if later_dep:
                raise UserError(_(
                    'Не можна скасувати модернізацію %s: на ОЗ "%s" '
                    'після %s проведено амортизацію (%s).'
                ) % (
                    line.modernization_id.name,
                    asset.display_name,
                    mod_date,
                    later_dep.date,
                ))
            # Check (b): no later confirmed modernization on same asset
            later_mod = self.env['l10n_ua.asset.modernization.line'].search([
                ('asset_id', '=', asset.id),
                ('state', '=', 'confirmed'),
                ('modernization_id.date', '>', mod_date),
                ('id', '!=', line.id),
            ], limit=1)
            if later_mod:
                raise UserError(_(
                    'Не можна скасувати модернізацію %s: на ОЗ "%s" '
                    'пізніше підтверджено модернізацію %s. Спочатку скасуйте її.'
                ) % (
                    line.modernization_id.name,
                    asset.display_name,
                    later_mod.modernization_id.name,
                ))
            vals = {'original_value': line.original_value_before}
            if line.useful_life_extension:
                vals['useful_life'] = line.useful_life_before
            asset.write(vals)
