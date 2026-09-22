"""Переоцінка валютних коштів (курсові різниці) — регламентна операція.

Перераховує залишки монетарних статей у валюті (валютні рахунки,
дебіторська/кредиторська заборгованість) за курсом НБУ на дату переоцінки
й формує проводки курсових різниць:
- додатна (актив дорожчає / зобовʼязання дешевшає) → дохід 714/744
- відʼємна → витрати 945/974
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Типи рахунків, що підлягають переоцінці (монетарні статті).
FX_MONETARY_TYPES = ('asset_receivable', 'liability_payable', 'asset_cash')


class AccountAccount(models.Model):
    _inherit = 'account.account'

    l10n_ua_fx_nonoperational = fields.Boolean(
        string='Неопераційна курсова різниця',
        help='Курсові різниці за цим рахунком відносити на неопераційні '
             'рахунки (744/974) замість операційних (714/945).',
    )


class L10nUaCurrencyRevaluation(models.Model):
    _name = 'l10n_ua.currency.revaluation'
    _description = 'Переоцінка валютних коштів (курсові різниці)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    name = fields.Char(compute='_compute_name', store=True)
    date = fields.Date(
        string='Дата переоцінки',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help='Дата, на яку перераховуються валютні залишки (кінець періоду).',
    )
    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    journal_id = fields.Many2one(
        'account.journal', string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help='Журнал для проводки курсових різниць.')
    state = fields.Selection(
        selection=[('draft', 'Чернетка'), ('posted', 'Проведено')],
        default='draft', tracking=True, copy=False)
    line_ids = fields.One2many(
        'l10n_ua.currency.revaluation.line', 'revaluation_id', string='Рядки')
    move_id = fields.Many2one(
        'account.move', string='Проводка', readonly=True, copy=False)
    total_gain = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    total_loss = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id')
    note = fields.Text(string='Примітки')

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Переоцінка валюти на %s') % (rec.date or _('нову'))

    @api.depends('line_ids.fx_difference')
    def _compute_totals(self):
        for rec in self:
            diffs = rec.line_ids.mapped('fx_difference')
            rec.total_gain = sum(d for d in diffs if d > 0)
            rec.total_loss = -sum(d for d in diffs if d < 0)

    def action_compute(self):
        """Розрахувати курсові різниці монетарних статей на дату переоцінки."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Переоцінку можна перерахувати лише в чернетці.'))
        if not self.date:
            raise UserError(_('Вкажіть дату переоцінки.'))

        self.line_ids.unlink()
        company = self.company_id
        company_currency = company.currency_id

        # Монетарні валютні рядки станом на дату переоцінки.
        rows = self.env['account.move.line']._read_group(
            [
                ('parent_state', '=', 'posted'),
                ('company_id', '=', company.id),
                ('date', '<=', self.date),
                ('currency_id', '!=', False),
                ('currency_id', '!=', company_currency.id),
                ('account_id.account_type', 'in', FX_MONETARY_TYPES),
            ],
            ['account_id', 'partner_id', 'currency_id'],
            ['amount_currency:sum', 'balance:sum'],
        )

        lines = []
        for account, partner, currency, fc_balance, book_balance in rows:
            if not fc_balance and not book_balance:
                continue
            # Переоцінена вартість = валютний залишок за курсом на дату.
            revalued = currency._l10n_ua_convert(
                fc_balance, company_currency, company, self.date)
            fx_diff = revalued - book_balance
            if company_currency.is_zero(fx_diff):
                continue
            lines.append((0, 0, {
                'account_id': account.id,
                'partner_id': partner.id if partner else False,
                'foreign_currency_id': currency.id,
                'fc_balance': fc_balance,
                'book_balance': book_balance,
                'revalued_balance': revalued,
                'fx_difference': fx_diff,
                'is_nonoperational': account.l10n_ua_fx_nonoperational,
            }))
        self.line_ids = lines
        return True

    def _fx_result_account(self, is_gain, is_nonoperational):
        """Рахунок доходу/витрат курсової різниці за конфігом компанії."""
        c = self.company_id
        if is_gain:
            acc = c.l10n_ua_fx_gain_nonop_account_id if is_nonoperational \
                else c.l10n_ua_fx_gain_op_account_id
        else:
            acc = c.l10n_ua_fx_loss_nonop_account_id if is_nonoperational \
                else c.l10n_ua_fx_loss_op_account_id
        return acc

    def action_post(self):
        """Сформувати й провести проводку курсових різниць."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Переоцінку вже проведено.'))
        if not self.line_ids:
            raise UserError(_('Немає різниць для проведення (спершу «Розрахувати»).'))
        journal = self.journal_id or self.env['account.journal'].search([
            ('type', '=', 'general'), ('company_id', '=', self.company_id.id)],
            limit=1)
        if not journal:
            raise UserError(_('Не знайдено загального журналу для проводки.'))

        move_lines = []
        for line in self.line_ids:
            is_gain = line.fx_difference > 0
            result_acc = self._fx_result_account(is_gain, line.is_nonoperational)
            if not result_acc:
                raise UserError(_(
                    'Не налаштовано рахунок %s курсової різниці (%s) у компанії.'
                ) % (
                    _('доходу') if is_gain else _('витрат'),
                    _('неопераційної') if line.is_nonoperational
                    else _('операційної')))
            diff = line.fx_difference
            # Монетарний рахунок отримує дельту балансу; результат — навпаки.
            move_lines.append((0, 0, {
                'account_id': line.account_id.id,
                'partner_id': line.partner_id.id or False,
                'debit': diff if diff > 0 else 0.0,
                'credit': -diff if diff < 0 else 0.0,
                'name': _('Курсова різниця %s') % line.foreign_currency_id.name,
            }))
            move_lines.append((0, 0, {
                'account_id': result_acc.id,
                'partner_id': line.partner_id.id or False,
                'debit': -diff if diff < 0 else 0.0,
                'credit': diff if diff > 0 else 0.0,
                'name': _('Курсова різниця %s') % line.foreign_currency_id.name,
            }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': self.name,
            'company_id': self.company_id.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.write({'move_id': move.id, 'state': 'posted'})
        return True

    def action_draft(self):
        """Повернути в чернетку (скасувати проводку, якщо була)."""
        self.ensure_one()
        if self.move_id:
            if self.move_id.state == 'posted':
                self.move_id.button_draft()
            self.move_id.unlink()
        self.write({'move_id': False, 'state': 'draft'})
        return True


class L10nUaCurrencyRevaluationLine(models.Model):
    _name = 'l10n_ua.currency.revaluation.line'
    _description = 'Рядок переоцінки валюти'
    _order = 'account_id, foreign_currency_id'

    revaluation_id = fields.Many2one(
        'l10n_ua.currency.revaluation', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='revaluation_id.company_id', store=True)
    currency_id = fields.Many2one(related='revaluation_id.currency_id')
    account_id = fields.Many2one('account.account', string='Рахунок', required=True)
    partner_id = fields.Many2one('res.partner', string='Партнер')
    foreign_currency_id = fields.Many2one('res.currency', string='Валюта')
    fc_balance = fields.Monetary(
        string='Залишок у валюті', currency_field='foreign_currency_id')
    book_balance = fields.Monetary(
        string='Балансова вартість', currency_field='currency_id')
    revalued_balance = fields.Monetary(
        string='Переоцінена вартість', currency_field='currency_id')
    fx_difference = fields.Monetary(
        string='Курсова різниця', currency_field='currency_id')
    is_nonoperational = fields.Boolean(string='Неопераційна')
