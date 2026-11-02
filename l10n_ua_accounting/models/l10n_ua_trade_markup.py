"""Списання торговельної націнки за середнім відсотком (НП(С)БО 9, п. 22) — #148.

Роздрібна торгівля, що обліковує товари за продажними цінами (282 «Товари в
торгівлі» за роздрібною вартістю, 285 «Торгова націнка»), визначає
собівартість реалізованого як різницю між продажною вартістю і націнкою на
нього. Націнку на реалізоване рахують раз на місяць:

    середній % = (націнка залишку на початок місяця + націнка надходжень за місяць)
                 / (продажна вартість залишку на початок + надходжень за місяць)
    націнка на вибуле = кредитовий оборот 282 за місяць × середній %

Списується Дт 285 Кт <рахунок, на який вибули товари>: 902 для продажу, 947
для нестач тощо. Рахунок береться з дебетових рядків тієї ж проводки, що
кредитує 282, пропорційно сумам — так 1С розносить націнку за кореспонденцією.

Розрахунок іде з оборотів Головної книги, а не зі складських рухів: оцінка
запасів Odoo живе за собівартістю (AVCO/ФІФО, п. 19–20), а продажні ціни
роздрібу — лише в бухгалтерії.
"""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaTradeMarkup(models.Model):
    _name = 'l10n_ua.trade.markup'
    _description = 'Trade Markup Write-off'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal())
    goods_account_id = fields.Many2one(
        'account.account', string='Goods at Retail Value',
        help='Account 282 «Товари в торгівлі», kept at retail (sale) prices.')
    markup_account_id = fields.Many2one(
        'account.account', string='Trade Markup',
        help='Account 285 «Торгова націнка».')
    default_account_id = fields.Many2one(
        'account.account', string='Default Disposal Account',
        help='Used when the entry that credits 282 has no other debit line '
             '(normally 902 «Собівартість реалізованих товарів»).')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry',
                              readonly=True, copy=False)
    closing_id = fields.Many2one('l10n_ua.period.closing', readonly=True, copy=False,
                                 help='The period closing that posted this write-off.')

    opening_retail = fields.Monetary(
        string='Opening Retail Value', readonly=True, copy=False,
        help='Debit balance of 282 at the start of the period.')
    received_retail = fields.Monetary(
        string='Received at Retail Value', readonly=True, copy=False,
        help='Debit turnover of 282 in the period.')
    opening_markup = fields.Monetary(
        string='Opening Markup', readonly=True, copy=False,
        help='Credit balance of 285 at the start of the period.')
    received_markup = fields.Monetary(
        string='Markup on Receipts', readonly=True, copy=False,
        help='Credit turnover of 285 in the period.')
    disposed_retail = fields.Monetary(
        string='Disposed at Retail Value', readonly=True, copy=False,
        help='Credit turnover of 282 in the period: sales, returns, shortages.')
    markup_percent = fields.Float(
        string='Average Markup, %', digits=(16, 4), readonly=True, copy=False)
    markup_amount = fields.Monetary(
        string='Markup to Write Off', readonly=True, copy=False)
    line_ids = fields.One2many('l10n_ua.trade.markup.line', 'markup_id',
                               string='Distribution', readonly=True, copy=False)

    _check_dates = models.Constraint(
        'CHECK(date_from <= date_to)',
        'The start date must not be after the end date.',
    )

    @api.depends('date_to')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Trade markup %s', rec.date_to.strftime('%m.%Y')) \
                if rec.date_to else _('New')

    def _default_journal(self):
        return self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    # ------------------------------------------------------------------ accounts

    def _find_account(self, prefix):
        self.ensure_one()
        return self.env['account.account'].with_company(self.company_id).search([
            ('code', '=like', prefix + '%'),
            ('company_ids', 'parent_of', self.company_id.id),
        ], order='code', limit=1)

    def _set_default_accounts(self):
        for rec in self:
            rec.goods_account_id = rec.goods_account_id or rec._find_account('282')
            rec.markup_account_id = rec.markup_account_id or rec._find_account('285')
            rec.default_account_id = rec.default_account_id or rec._find_account('902')

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.goods_account_id = self.markup_account_id = self.default_account_id = False
        self._set_default_accounts()

    # --------------------------------------------------------------- computation

    def _aml_domain(self, account, date_from=None, date_to=None):
        domain = [
            ('account_id', '=', account.id),
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    def _sum(self, domain, field):
        groups = self.env['account.move.line']._read_group(domain, [], [f'{field}:sum'])
        return groups[0][0] or 0.0

    def _disposals_by_account(self):
        """Credit turnover of 282 split by the account the goods went to."""
        self.ensure_one()
        goods, markup = self.goods_account_id, self.markup_account_id
        by_account = defaultdict(float)
        credit_lines = self.env['account.move.line'].search(
            self._aml_domain(goods, self.date_from, self.date_to) + [('credit', '!=', 0)])
        for move, lines in credit_lines.grouped('move_id').items():
            credited = sum(lines.mapped('credit'))
            counter = move.line_ids.filtered(
                lambda l: l.debit and l.account_id not in (goods | markup))
            total = sum(counter.mapped('debit'))
            if not total:
                by_account[self.default_account_id] += credited
                continue
            for line in counter:
                by_account[line.account_id] += credited * line.debit / total
        return by_account

    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft write-off can be computed.'))
            rec._set_default_accounts()
            if not (rec.goods_account_id and rec.markup_account_id and rec.default_account_id):
                raise UserError(_(
                    'Set the accounts of goods at retail value (282), trade '
                    'markup (285) and the default disposal account (902).'))
            goods, markup = rec.goods_account_id, rec.markup_account_id
            day_before = fields.Date.subtract(rec.date_from, days=1)
            rec.opening_retail = rec._sum(rec._aml_domain(goods, date_to=day_before), 'balance')
            rec.opening_markup = -rec._sum(rec._aml_domain(markup, date_to=day_before), 'balance')
            period = (rec.date_from, rec.date_to)
            rec.received_retail = rec._sum(rec._aml_domain(goods, *period), 'debit')
            rec.received_markup = rec._sum(rec._aml_domain(markup, *period), 'credit')
            rec.disposed_retail = rec._sum(rec._aml_domain(goods, *period), 'credit')

            base = rec.opening_retail + rec.received_retail
            ratio = (rec.opening_markup + rec.received_markup) / base if base else 0.0
            rec.markup_percent = ratio * 100
            currency = rec.currency_id

            lines = []
            for account, retail in sorted(rec._disposals_by_account().items(),
                                          key=lambda item: item[0].code or ''):
                lines.append({
                    'account_id': account.id,
                    'retail_amount': currency.round(retail),
                    'markup_amount': currency.round(retail * ratio),
                })
            # The total is computed once and the rounding difference goes to
            # the largest line, so the entry matches retail × average %.
            total = currency.round(rec.disposed_retail * ratio)
            if lines:
                diff = currency.round(total - sum(l['markup_amount'] for l in lines))
                if diff:
                    max(lines, key=lambda l: abs(l['markup_amount']))['markup_amount'] += diff
            rec.markup_amount = total
            rec.line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in lines]
        return True

    # -------------------------------------------------------------------- posting

    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft write-off can be posted.'))
            rec.action_compute()
            overlap = self.search([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('state', '=', 'posted'),
                ('date_from', '<=', rec.date_to),
                ('date_to', '>=', rec.date_from),
            ], limit=1)
            if overlap:
                raise UserError(_(
                    'Trade markup is already written off for this period: %s.',
                    overlap.name))
            move = False
            lines = rec.line_ids.filtered(lambda l: not rec.currency_id.is_zero(l.markup_amount))
            if lines:
                move_lines = [(0, 0, {
                    'account_id': line.account_id.id,
                    'name': _('Trade markup on disposed goods'),
                    'credit': line.markup_amount,
                }) for line in lines]
                move_lines.append((0, 0, {
                    'account_id': rec.markup_account_id.id,
                    'name': _('Trade markup write-off, average %s %%',
                              round(rec.markup_percent, 2)),
                    'debit': sum(lines.mapped('markup_amount')),
                }))
                move = self.env['account.move'].with_company(rec.company_id).create({
                    'move_type': 'entry',
                    'journal_id': rec.journal_id.id,
                    'date': rec.date_to,
                    'ref': rec.name,
                    'line_ids': move_lines,
                })
                move.action_post()
            rec.write({'state': 'posted', 'move_id': move and move.id})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id._reverse_moves(default_values_list=[{
                    'date': rec.date_to,
                    'ref': _('Reversal: %s', rec.name),
                }], cancel=True)
            rec.write({'state': 'cancelled', 'closing_id': False})
        return True

    def action_draft(self):
        self.filtered(lambda r: r.state == 'cancelled').write(
            {'state': 'draft', 'move_id': False})
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }


class L10nUaTradeMarkupLine(models.Model):
    _name = 'l10n_ua.trade.markup.line'
    _description = 'Trade Markup Write-off Line'
    _order = 'id'

    markup_id = fields.Many2one('l10n_ua.trade.markup', required=True,
                                ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='markup_id.currency_id')
    account_id = fields.Many2one('account.account', string='Disposal Account',
                                 required=True)
    retail_amount = fields.Monetary(string='Disposed at Retail Value')
    markup_amount = fields.Monetary(string='Markup')


class L10nUaPeriodClosing(models.Model):
    _inherit = 'l10n_ua.period.closing'

    def _post_trade_markup(self):
        """Write off the trade markup before the 9x accounts are closed.

        Draft write-offs of the period are posted; if goods at retail value
        left 282 in the period and nothing is posted yet, one is created.
        Companies that do not use 282 are not affected.
        """
        self.ensure_one()
        Markup = self.env['l10n_ua.trade.markup']
        start, end = self.period_id.date_start, self.period_id.date_end
        period_domain = [
            ('company_id', '=', self.company_id.id),
            ('date_from', '<=', end),
            ('date_to', '>=', start),
        ]
        for draft in Markup.search(period_domain + [('state', '=', 'draft')]):
            draft.action_post()
            draft.closing_id = self
        if Markup.search_count(period_domain + [('state', '=', 'posted')]):
            return
        markup = Markup.new({'company_id': self.company_id.id})
        markup._set_default_accounts()
        if not (markup.goods_account_id and markup.markup_account_id):
            return
        disposed = markup._sum(
            [('account_id', '=', markup.goods_account_id.id),
             ('company_id', '=', self.company_id.id),
             ('parent_state', '=', 'posted'),
             ('date', '>=', start), ('date', '<=', end)], 'credit')
        if self.company_id.currency_id.is_zero(disposed):
            return
        markup = Markup.create({
            'company_id': self.company_id.id,
            'date_from': start,
            'date_to': end,
            'journal_id': self.journal_id.id,
        })
        markup.action_post()
        markup.closing_id = self

    def _post_deferral_entries(self):
        res = super()._post_deferral_entries()
        self._post_trade_markup()
        return res

    def _reverse_deferral_entries(self):
        res = super()._reverse_deferral_entries()
        self.env['l10n_ua.trade.markup'].search([
            ('closing_id', '=', self.id), ('state', '=', 'posted'),
        ]).action_cancel()
        return res
