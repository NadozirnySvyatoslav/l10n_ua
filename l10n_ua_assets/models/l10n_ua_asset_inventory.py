"""Інвентаризація ОЗ — П(С)БО 7 + Наказ Мінфіну №879 (Інв-1, Інв-3)."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaAssetInventory(models.Model):
    _name = 'l10n_ua.asset.inventory'
    _description = 'Інвентаризація основних засобів'
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
        string='Дата інвентаризації',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('in_progress', 'У процесі'),
            ('done', 'Завершено'),
            ('cancelled', 'Скасовано'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
        copy=False,
    )

    # --- Підстава ---
    order_number = fields.Char(string='№ наказу про інвентаризацію')
    order_date = fields.Date(string='Дата наказу')
    commission_chair_id = fields.Many2one(
        'hr.employee',
        string='Голова комісії',
    )

    # --- Фільтри для заповнення ---
    filter_group_id = fields.Many2one(
        'l10n_ua.asset.group',
        string='Група ОЗ',
        help='Фільтр для дії «Заповнити рядки»',
    )
    filter_responsible_id = fields.Many2one(
        'hr.employee',
        string='МВО',
        help='Фільтр для дії «Заповнити рядки»',
    )
    filter_location = fields.Char(string='Місцезнаходження (фільтр)')

    # --- Рядки ---
    line_ids = fields.One2many(
        'l10n_ua.asset.inventory.line',
        'inventory_id',
        string='Рядки',
        copy=False,
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
    accumulated_depreciation_account_id = fields.Many2one(
        'account.account',
        string='Рахунок зносу (131)',
        domain="[('company_ids', 'in', company_id)]",
    )
    shortage_expense_account_id = fields.Many2one(
        'account.account',
        string='Нестачі (947)',
        domain="[('company_ids', 'in', company_id)]",
        help='Витрати на списання нестач (947)',
    )
    surplus_income_account_id = fields.Many2one(
        'account.account',
        string='Лишки (746)',
        domain="[('company_ids', 'in', company_id)]",
        help='Інші доходи від лишків (746)',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
    )

    # --- Підсумки ---
    line_count = fields.Integer(
        string='Усього рядків',
        compute='_compute_summary',
        store=True,
    )
    matched_count = fields.Integer(
        string='Підтверджено',
        compute='_compute_summary',
        store=True,
    )
    shortage_count = fields.Integer(
        string='Нестачі',
        compute='_compute_summary',
        store=True,
    )
    surplus_count = fields.Integer(
        string='Лишки',
        compute='_compute_summary',
        store=True,
    )
    shortage_amount = fields.Monetary(
        string='Сума нестач',
        compute='_compute_summary',
        store=True,
        currency_field='currency_id',
    )
    surplus_amount = fields.Monetary(
        string='Сума лишків',
        compute='_compute_summary',
        store=True,
        currency_field='currency_id',
    )

    notes = fields.Text(string='Примітки')

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

    @api.depends('line_ids.discrepancy', 'line_ids.book_value',
                 'line_ids.surplus_value')
    def _compute_summary(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.matched_count = len(rec.line_ids.filtered(
                lambda l: l.discrepancy == 'match'))
            shortage = rec.line_ids.filtered(lambda l: l.discrepancy == 'shortage')
            surplus = rec.line_ids.filtered(lambda l: l.discrepancy == 'surplus')
            rec.shortage_count = len(shortage)
            rec.surplus_count = len(surplus)
            rec.shortage_amount = sum(shortage.mapped('book_value'))
            rec.surplus_amount = sum(surplus.mapped('surplus_value'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Нова'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.asset.inventory'
                ) or _('Нова')
        return super().create(vals_list)

    # --- Дії ---

    def action_fill_lines(self):
        """Заповнити рядки активами, що відповідають фільтрам.

        Можна повторно викликати у стані «У процесі» — додає лише ОЗ,
        яких ще немає у списку.
        """
        self.ensure_one()
        if self.state not in ('draft', 'in_progress'):
            raise UserError(_(
                'Заповнити рядки можна лише в стані «Чернетка» або «У процесі».'
            ))
        domain = [
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ['open', 'paused']),
        ]
        if self.filter_group_id:
            domain.append(('group_id', '=', self.filter_group_id.id))
        if self.filter_responsible_id:
            domain.append(('responsible_id', '=', self.filter_responsible_id.id))
        if self.filter_location:
            domain.append(('location', 'ilike', self.filter_location))
        # Виключити вже додані
        existing_asset_ids = self.line_ids.mapped('asset_id').ids
        if existing_asset_ids:
            domain.append(('id', 'not in', existing_asset_ids))
        assets = self.env['l10n_ua.asset'].search(domain)
        Line = self.env['l10n_ua.asset.inventory.line']
        for asset in assets:
            Line.create({
                'inventory_id': self.id,
                'asset_id': asset.id,
                'book_value': asset.book_value,
                'accumulated_depreciation': asset.accumulated_depreciation,
                'original_value': asset.original_value,
            })
        if self.state == 'draft':
            self.state = 'in_progress'
        return True

    def action_add_surplus(self):
        """Додати порожній рядок для лишку (виявлений ОЗ не в обліку)."""
        self.ensure_one()
        if self.state not in ('draft', 'in_progress'):
            raise UserError(_('Лишок можна додати лише в стані «Чернетка» або «У процесі».'))
        if self.state == 'draft':
            self.state = 'in_progress'
        Line = self.env['l10n_ua.asset.inventory.line']
        Line.create({
            'inventory_id': self.id,
            'is_surplus': True,
            'found': True,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_done(self):
        """Завершити інвентаризацію: списати нестачі, оприбуткувати лишки,
        створити бухгалтерську проводку.
        """
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_(
                    'Завершити можна лише інвентаризацію у процесі. '
                    'Спочатку заповніть рядки.'
                ))
            unmarked = rec.line_ids.filtered(
                lambda l: not l.is_surplus and not l.found and not l.processed)
            shortage_lines = unmarked
            surplus_lines = rec.line_ids.filtered(
                lambda l: l.is_surplus and not l.processed)
            if not shortage_lines and not surplus_lines:
                rec.state = 'done'
                continue
            rec._validate_accounts(shortage_lines, surplus_lines)
            shortage_lines._process_shortage()
            surplus_lines._process_surplus()
            rec._create_account_move(shortage_lines, surplus_lines)
            rec.state = 'done'
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_(
                    'Не можна скасувати завершену інвентаризацію (нестачі '
                    'та лишки вже відображені в обліку). Створіть зворотний документ.'
                ))
            if rec.state == 'cancelled':
                continue
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('У чернетку можна повернути лише скасовану.'))
            rec.state = 'draft'
        return True

    def action_print_inv1(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_assets.action_report_asset_inv1').report_action(self)

    def action_print_inv3(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_assets.action_report_asset_inv3').report_action(self)

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            'name': _('Проводка інвентаризації'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _validate_accounts(self, shortage_lines, surplus_lines):
        self.ensure_one()
        missing = []
        if shortage_lines or surplus_lines:
            if not self.journal_id:
                missing.append(_('Журнал'))
            if not self.fixed_asset_account_id:
                missing.append(_('Рахунок ОЗ (10)'))
            if not self.accumulated_depreciation_account_id:
                missing.append(_('Рахунок зносу (131)'))
        if shortage_lines and not self.shortage_expense_account_id:
            missing.append(_('Рахунок нестач (947)'))
        if surplus_lines and not self.surplus_income_account_id:
            missing.append(_('Рахунок лишків (746)'))
        if missing:
            raise UserError(_(
                'Не заповнено обов\'язкові поля: %s'
            ) % ', '.join(missing))

    def _create_account_move(self, shortage_lines, surplus_lines):
        """Створити проводку інвентаризації.

        Нестачі (для кожного активу):
            Дт 131 (накопич. знос)         / Кт 10 (на знос)
            Дт 947 (нестачі)               / Кт 10 (на залишкову вартість)
        Лишки (за справедливою вартістю):
            Дт 10                          / Кт 746 (інші доходи)
        """
        self.ensure_one()
        move_lines = []
        ref = _('Інвентаризація ОЗ %s від %s') % (self.name, self.date)

        for line in shortage_lines:
            asset_name = line.asset_id.name
            # Списати накопичений знос: Дт 131 / Кт 10
            if line.accumulated_depreciation:
                move_lines.append((0, 0, {
                    'account_id': self.accumulated_depreciation_account_id.id,
                    'name': _('Нестача (знос): %s') % asset_name,
                    'debit': line.accumulated_depreciation,
                    'credit': 0.0,
                }))
                move_lines.append((0, 0, {
                    'account_id': self.fixed_asset_account_id.id,
                    'name': _('Нестача (знос): %s') % asset_name,
                    'debit': 0.0,
                    'credit': line.accumulated_depreciation,
                }))
            # Списати залишкову вартість: Дт 947 / Кт 10
            if line.book_value:
                move_lines.append((0, 0, {
                    'account_id': self.shortage_expense_account_id.id,
                    'name': _('Нестача (залишкова): %s') % asset_name,
                    'debit': line.book_value,
                    'credit': 0.0,
                }))
                move_lines.append((0, 0, {
                    'account_id': self.fixed_asset_account_id.id,
                    'name': _('Нестача (залишкова): %s') % asset_name,
                    'debit': 0.0,
                    'credit': line.book_value,
                }))

        for line in surplus_lines:
            if not line.surplus_value:
                continue
            asset_name = line.surplus_name or _('Лишок')
            # Оприбуткувати: Дт 10 / Кт 746
            move_lines.append((0, 0, {
                'account_id': self.fixed_asset_account_id.id,
                'name': _('Лишок: %s') % asset_name,
                'debit': line.surplus_value,
                'credit': 0.0,
            }))
            move_lines.append((0, 0, {
                'account_id': self.surplus_income_account_id.id,
                'name': _('Лишок: %s') % asset_name,
                'debit': 0.0,
                'credit': line.surplus_value,
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
            if rec.state == 'done':
                raise UserError(_(
                    'Не можна видалити завершену інвентаризацію.'
                ))
        return super().unlink()


class L10nUaAssetInventoryLine(models.Model):
    _name = 'l10n_ua.asset.inventory.line'
    _description = 'Рядок інвентаризації ОЗ'
    _order = 'inventory_id, is_surplus, id'

    inventory_id = fields.Many2one(
        'l10n_ua.asset.inventory',
        string='Інвентаризація',
        required=True,
        ondelete='cascade',
    )
    asset_id = fields.Many2one(
        'l10n_ua.asset',
        string='Основний засіб',
        ondelete='restrict',
        help='Заповнено для існуючих ОЗ; порожнє для лишків',
    )

    # Snapshot
    original_value = fields.Monetary(
        string='Первісна вартість',
        currency_field='currency_id',
    )
    accumulated_depreciation = fields.Monetary(
        string='Знос',
        currency_field='currency_id',
    )
    book_value = fields.Monetary(
        string='Залишкова вартість',
        currency_field='currency_id',
    )

    # Поточна перевірка
    found = fields.Boolean(
        string='Знайдено',
        default=False,
        help='Фактично присутній на місці',
    )
    condition_note = fields.Char(string='Стан / примітки')

    # Лишок
    is_surplus = fields.Boolean(string='Лишок', default=False)
    surplus_name = fields.Char(string='Найменування лишку')
    surplus_value = fields.Monetary(
        string='Справедлива вартість лишку',
        currency_field='currency_id',
    )
    created_asset_id = fields.Many2one(
        'l10n_ua.asset',
        string='Створений ОЗ',
        readonly=True,
        help='Створений на основі цього лишку',
    )

    # Обробка
    processed = fields.Boolean(
        string='Опрацьовано',
        default=False,
        readonly=True,
    )

    discrepancy = fields.Selection(
        selection=[
            ('match', 'Збіг'),
            ('shortage', 'Нестача'),
            ('surplus', 'Лишок'),
        ],
        string='Розбіжність',
        compute='_compute_discrepancy',
        store=True,
    )

    state = fields.Selection(
        related='inventory_id.state',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='inventory_id.currency_id',
    )

    @api.depends('is_surplus', 'found')
    def _compute_discrepancy(self):
        for line in self:
            if line.is_surplus:
                line.discrepancy = 'surplus'
            elif line.found:
                line.discrepancy = 'match'
            else:
                line.discrepancy = 'shortage'

    def _process_shortage(self):
        """Списати ОЗ як нестачу."""
        for line in self:
            asset = line.asset_id
            if not asset:
                continue
            asset.write({
                'state': 'close',
                'writeoff_date': line.inventory_id.date,
                'writeoff_reason': _('Нестача за інвентаризацією %s') % line.inventory_id.name,
            })
            line.processed = True

    def _process_surplus(self):
        """Створити новий ОЗ для лишку."""
        Asset = self.env['l10n_ua.asset']
        for line in self:
            if not line.surplus_value:
                continue
            new_asset = Asset.create({
                'name': line.surplus_name or _('Лишок %s') % line.inventory_id.name,
                'acquisition_date': line.inventory_id.date,
                'original_value': line.surplus_value,
                'company_id': line.inventory_id.company_id.id,
                'state': 'open',
                'commission_date': line.inventory_id.date,
            })
            line.created_asset_id = new_asset
            line.processed = True
