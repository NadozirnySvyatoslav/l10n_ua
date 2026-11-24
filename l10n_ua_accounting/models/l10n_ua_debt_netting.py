"""Взаємозалік зустрічних однорідних вимог (#371).

Документ гасить зустрічні борги з одним контрагентом (ст. 601 ЦКУ):
наша вимога до нього (дебетове сальдо 361, 371, 377…) зараховується в
рахунок його вимоги до нас (кредитове сальдо 631, 685, 681…).

Проводка будується «по документу»: на кожен відкритий рядок розрахунків,
який бере участь у заліку, — зустрічний рядок на тому самому рахунку,
і кожна пара одразу зіставляється (`reconcile`). Так часткове погашення
лягає саме на той документ, який обрав розподіл, а не на той, що першим
трапиться ядру при груповому зіставленні. У підсумку проводка виглядає як
Дт 631 (685…) — Кт 361 (371…) на суму заліку.

Розподіл суми заліку між документами кожної сторони — FIFO: спершу
найстаріші за строком оплати.

Скасування — сторно: зіставлення знімається, проводка реверсується
(`_reverse_moves(cancel=True)`), залишки документів повертаються.

ПДВ при касовому методі окремо не обробляємо: `l10n_ua_account_vat`
вважає першою подією будь-яке зіставлення рядка розрахунків, зокрема й
залік (п. 187.10 ПКУ, «інші види компенсацій»).
"""

from datetime import date as date_cls

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

from odoo.addons.l10n_ua_account_base.tools.formatters import (
    amount_to_words_ua,
    format_date_ua,
)

SIDES = [
    ('receivable', 'Owed to us'),
    ('payable', 'Owed by us'),
]


class L10nUaDebtNetting(models.Model):
    _name = 'l10n_ua.debt.netting'
    _description = 'Debt Netting'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Number', required=True, copy=False, readonly=True,
        default='/', tracking=True)
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
        tracking=True,
        help='Date of the netting: the accounting date of the journal entry.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    company_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Company Currency')
    partner_id = fields.Many2one(
        'res.partner', string='Partner', required=True, tracking=True,
        check_company=True,
        domain="['|', ('parent_id', '=', False), ('is_company', '=', True)]")
    commercial_partner_id = fields.Many2one(
        related='partner_id.commercial_partner_id')
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        check_company=True, domain="[('type', '=', 'general')]",
        default=lambda self: self._default_journal())
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True, tracking=True,
        default=lambda self: self.env.company.currency_id,
        help='Only documents in this currency can be offset against each '
             'other.')

    line_ids = fields.One2many(
        'l10n_ua.debt.netting.line', 'netting_id', string='Documents',
        copy=False)
    receivable_line_ids = fields.One2many(
        'l10n_ua.debt.netting.line', 'netting_id',
        string='Partner Debts', domain=[('side', '=', 'receivable')],
        copy=False)
    payable_line_ids = fields.One2many(
        'l10n_ua.debt.netting.line', 'netting_id',
        string='Our Debts', domain=[('side', '=', 'payable')],
        copy=False)

    amount_receivable = fields.Monetary(
        string='Partner Owes Us', compute='_compute_totals', store=True,
        help='Open amount of the selected documents on which the partner '
             'owes the company.')
    amount_payable = fields.Monetary(
        string='We Owe the Partner', compute='_compute_totals', store=True,
        help='Open amount of the selected documents on which the company '
             'owes the partner.')
    amount_max = fields.Monetary(
        string='Maximum Offset', compute='_compute_totals', store=True)
    amount = fields.Monetary(
        string='Offset Amount', compute='_compute_amount', store=True,
        readonly=False, tracking=True,
        help='Amount of mutual claims to be offset. Defaults to the smaller '
             'of the two sides and cannot exceed it.')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', required=True, default='draft', copy=False,
        tracking=True)
    move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False,
        check_company=True)
    reversal_move_id = fields.Many2one(
        'account.move', string='Reversal Entry', readonly=True, copy=False,
        check_company=True)
    note = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Defaults / computes
    # ------------------------------------------------------------------

    @api.model
    def _default_journal(self):
        return self.env['account.journal'].search([
            *self.env['account.journal']._check_company_domain(
                self.env.company),
            ('type', '=', 'general'),
        ], limit=1)

    # Залежимо від двох «половинок», а не від line_ids: у формі є лише вони,
    # і onchange інакше не побачив би щойно доданих рядків.
    @api.depends('receivable_line_ids.amount_open',
                 'payable_line_ids.amount_open')
    def _compute_totals(self):
        for rec in self:
            rec.amount_receivable = sum(
                rec.receivable_line_ids.mapped('amount_open'))
            rec.amount_payable = sum(
                rec.payable_line_ids.mapped('amount_open'))
            rec.amount_max = min(rec.amount_receivable, rec.amount_payable)

    @api.depends('amount_max')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.amount_max

    def _allocate(self):
        """Розподіл суми заліку по документах кожної сторони (FIFO).

        :return: {рядок документа: сума заліку по ньому}
        """
        self.ensure_one()
        result = {}
        for side_lines in (self.receivable_line_ids, self.payable_line_ids):
            remaining = self.amount
            lines = side_lines.sorted(
                lambda l: (l.date_maturity or l.date or date_cls.max,
                           l.move_line_id.id or 0))
            for line in lines:
                part = self.currency_id.round(
                    min(line.amount_open, max(remaining, 0.0)))
                result[line] = part
                remaining -= part
        return result

    # ------------------------------------------------------------------
    # CRUD / constraints
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(
                    vals.get('company_id')) or self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(
                    company).next_by_code('l10n_ua.debt.netting') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state == 'posted' for rec in self):
            raise UserError(_(
                'A posted debt netting cannot be deleted. Cancel it first.'))
        return super().unlink()

    @api.constrains('amount', 'amount_max')
    def _check_amount(self):
        for rec in self:
            prec = rec.currency_id.decimal_places
            if float_compare(rec.amount, 0.0, precision_digits=prec) < 0:
                raise ValidationError(_(
                    'The offset amount cannot be negative.'))
            if float_compare(rec.amount, rec.amount_max,
                             precision_digits=prec) > 0:
                raise ValidationError(_(
                    'The offset amount %(amount)s exceeds the smaller side of '
                    'the mutual claims (%(max)s).',
                    amount=rec.amount, max=rec.amount_max))

    @api.constrains('partner_id', 'currency_id', 'company_id')
    def _check_header(self):
        self.line_ids._check_move_line()

    # ------------------------------------------------------------------
    # Selection of open items
    # ------------------------------------------------------------------

    def _get_candidate_domain(self):
        """Відкриті рядки розрахунків контрагента у валюті документа.

        Беремо будь-який рахунок із прапорцем зіставлення, а не лише
        тип receivable/payable: аванси видані (371) у плані рахунків —
        `asset_current`, а залік 371/685 — типовий сценарій.
        """
        self.ensure_one()
        return [
            ('company_id', '=', self.company_id.id),
            ('partner_id', 'child_of', self.commercial_partner_id.id),
            ('parent_state', '=', 'posted'),
            ('account_id.reconcile', '=', True),
            ('account_id.account_type', 'not in',
             ('asset_cash', 'liability_credit_card')),
            ('reconciled', '=', False),
            ('currency_id', '=', self.currency_id.id),
            ('amount_residual_currency', '!=', 0.0),
        ]

    def action_fill_lines(self):
        """Підтягнути всі відкриті документи контрагента."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft netting can be edited.'))
            existing = rec.line_ids.move_line_id
            move_lines = self.env['account.move.line'].search(
                rec._get_candidate_domain()
                + [('id', 'not in', existing.ids)],
                order='date_maturity, date, id')
            if not move_lines and not existing:
                raise UserError(_(
                    'Partner %(partner)s has no open items in %(currency)s.',
                    partner=rec.partner_id.display_name,
                    currency=rec.currency_id.name))
            rec.line_ids = [
                Command.create({'move_line_id': ml.id}) for ml in move_lines]
        return True

    def action_clear_lines(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft netting can be edited.'))
            rec.line_ids = [Command.clear()]
        return True

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def _refresh_open_amounts(self):
        """Оновити залишки документів на момент проведення.

        Між складанням чернетки й проведенням документ могли частково
        оплатити. Обрану користувачем суму заліку зберігаємо, якщо вона
        все ще вкладається в нові залишки.
        """
        self.ensure_one()
        amount = self.amount
        for line in self.line_ids:
            live = line._get_live_residual()
            if self.currency_id.is_zero(live):
                raise UserError(_(
                    'Document %(document)s is already settled. Remove it '
                    'from the netting.', document=line.move_id.display_name))
            if self.currency_id.compare_amounts(live, line.amount_open):
                line.amount_open = live
        if self.currency_id.compare_amounts(amount, self.amount_max) > 0:
            raise UserError(_(
                'Open amounts of the documents have changed: the offset '
                'amount %(amount)s now exceeds the maximum of %(max)s.',
                amount=amount, max=self.amount_max))
        if self.currency_id.compare_amounts(amount, self.amount):
            self.amount = amount

    def _prepare_move_line_vals(self):
        """Зустрічні рядки проводки: по одному на кожен документ заліку.

        Кредитуємо рахунок кожної нашої вимоги і дебетуємо рахунок кожного
        нашого боргу на суму, що припадає на документ. У валюті компанії
        обидві сторони переводяться за курсом на дату заліку; копійки
        округлення кожної сторони сходяться на її останньому рядку, тож
        проводка завжди збалансована.

        :return: list of (netting line, vals)
        """
        self.ensure_one()
        company_currency = self.company_currency_id
        total_balance = self.currency_id._convert(
            self.amount, company_currency, self.company_id, self.date)
        result = []
        for side, sign in (('payable', 1), ('receivable', -1)):
            lines = self.line_ids.filtered(
                lambda l: l.side == side
                and not self.currency_id.is_zero(l.amount_offset)
            ).sorted(lambda l: (l.date_maturity or l.date or date_cls.max,
                                l.move_line_id.id))
            side_balance = 0.0
            for idx, line in enumerate(lines):
                if idx == len(lines) - 1:
                    balance = company_currency.round(
                        total_balance - side_balance)
                else:
                    balance = self.currency_id._convert(
                        line.amount_offset, company_currency,
                        self.company_id, self.date)
                side_balance += balance
                ml = line.move_line_id
                result.append((line, {
                    'name': _('Debt netting %(number)s: %(document)s',
                              number=self.name,
                              document=ml.move_id.name),
                    'account_id': ml.account_id.id,
                    'partner_id': ml.partner_id.id,
                    'currency_id': self.currency_id.id,
                    'amount_currency': sign * line.amount_offset,
                    'balance': sign * balance,
                }))
        return result

    def _prepare_move_vals(self, prepared):
        """Значення проводки заліку; точка розширення (договір тощо)."""
        self.ensure_one()
        return {
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': _('Debt netting %s', self.name),
            'partner_id': self.commercial_partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'line_ids': [Command.create(vals) for _line, vals in prepared],
        }

    def _check_can_post(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft netting can be posted.'))
        sides = set(self.line_ids.mapped('side'))
        if sides != {'receivable', 'payable'}:
            raise UserError(_(
                'A netting needs open documents on both sides: debts of the '
                'partner to the company and debts of the company to the '
                'partner.'))
        if self.currency_id.is_zero(self.amount):
            raise UserError(_('The offset amount must be positive.'))

    def action_post(self):
        for rec in self:
            rec._check_can_post()
            rec._refresh_open_amounts()
            prepared = rec._prepare_move_line_vals()
            move = self.env['account.move'].create(
                rec._prepare_move_vals(prepared))
            move.action_post()
            # Рядки проводки створюються в порядку команд — зіставляємо
            # кожен зі своїм документом.
            counterparts = move.line_ids.sorted('id')
            for (line, _vals), counterpart in zip(prepared, counterparts):
                if counterpart.account_id != line.move_line_id.account_id:
                    raise UserError(_(
                        'Internal error: unexpected order of journal items.'))
                line.counterpart_line_id = counterpart
                (counterpart | line.move_line_id).reconcile()
            rec.write({'move_id': move.id, 'state': 'posted'})
        return True

    def action_cancel(self):
        """Скасування: зняти зіставлення і сторнувати проводку."""
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state == 'cancel':
                continue
            if rec.state == 'posted' and rec.move_id:
                rec.move_id.line_ids.remove_move_reconcile()
                reversal = rec.move_id._reverse_moves([{
                    'date': max(rec.date, today),
                    'ref': _('Cancellation of debt netting %s', rec.name),
                }], cancel=True)
                rec.reversal_move_id = reversal
            rec.state = 'cancel'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancel':
                raise UserError(_(
                    'Only a cancelled netting can be reset to draft.'))
            rec.line_ids.counterpart_line_id = False
            rec.write({
                'state': 'draft',
                'move_id': False,
                'reversal_move_id': False,
            })
        return True

    def action_view_move(self):
        self.ensure_one()
        moves = self.move_id | self.reversal_move_id
        action = {
            'name': _('Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'create': False},
        }
        if len(moves) == 1:
            action.update({'view_mode': 'form', 'res_id': moves.id})
        else:
            action.update({'view_mode': 'list,form',
                           'domain': [('id', 'in', moves.ids)]})
        return action

    # ------------------------------------------------------------------
    # Printing helpers
    # ------------------------------------------------------------------

    def _get_print_lines(self, side):
        """Документи сторони, що фактично беруть участь у заліку."""
        self.ensure_one()
        return self.line_ids.filtered(
            lambda l: l.side == side
            and not self.currency_id.is_zero(l.amount_offset)
        ).sorted(lambda l: (l.date_maturity or l.date or date_cls.max,
                            l.move_line_id.id))

    def _get_amount_words(self):
        self.ensure_one()
        if self.currency_id.name == 'UAH':
            words = amount_to_words_ua(self.amount)
        else:
            # Валютну суму прописом дає ядро (num2words) — українською,
            # якщо мову встановлено.
            currency = self.currency_id
            if 'uk_UA' in dict(self.env['res.lang'].get_installed()):
                currency = currency.with_context(lang='uk_UA')
            words = currency.amount_to_text(self.amount)
        return words[:1].upper() + words[1:] if words else ''

    def _get_date_long(self):
        self.ensure_one()
        return format_date_ua(self.date)

    def _format_date_short(self, value):
        return format_date_ua(value, 'short') if value else ''

    def _get_print_amount(self, amount):
        return '{:,.2f}'.format(amount or 0.0).replace(',', ' ')


class L10nUaDebtNettingLine(models.Model):
    _name = 'l10n_ua.debt.netting.line'
    _description = 'Debt Netting Document'
    _order = 'netting_id, side, date_maturity, id'
    _check_company_auto = True

    netting_id = fields.Many2one(
        'l10n_ua.debt.netting', string='Debt Netting', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='netting_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='netting_id.currency_id')
    move_line_id = fields.Many2one(
        'account.move.line', string='Journal Item', required=True,
        ondelete='restrict', check_company=True, index=True)
    move_id = fields.Many2one(
        related='move_line_id.move_id', string='Document')
    account_id = fields.Many2one(
        related='move_line_id.account_id', string='Account')
    date = fields.Date(related='move_line_id.date', string='Date')
    date_maturity = fields.Date(
        related='move_line_id.date_maturity', string='Due Date')
    ref = fields.Char(related='move_line_id.move_id.ref', string='Reference')
    side = fields.Selection(
        selection=SIDES, string='Side', compute='_compute_side', store=True,
        help='Whose debt this document is: the partner owes us (debit '
             'balance) or we owe the partner (credit balance).')
    amount_open = fields.Monetary(
        string='Open Amount', compute='_compute_amount_open', store=True,
        readonly=False,
        help='Unsettled amount of the document in the netting currency, '
             'taken when the document was added and refreshed on posting.')
    amount_offset = fields.Monetary(
        string='Offset', compute='_compute_amount_offset', store=True)
    amount_after = fields.Monetary(
        string='Remaining', compute='_compute_amount_offset', store=True)
    counterpart_line_id = fields.Many2one(
        'account.move.line', string='Netting Journal Item', readonly=True,
        copy=False)

    _netting_move_line_uniq = models.Constraint(
        'UNIQUE(netting_id, move_line_id)',
        'The same document cannot be added to a netting twice.',
    )

    def _get_live_residual(self):
        """Поточний залишок документа у валюті заліку (за модулем)."""
        self.ensure_one()
        return abs(self.move_line_id.amount_residual_currency)

    @api.depends('move_line_id')
    def _compute_side(self):
        for line in self:
            ml = line.move_line_id
            value = ml.amount_residual_currency or ml.balance
            line.side = 'receivable' if value > 0 else 'payable' if value else False

    @api.depends('move_line_id')
    def _compute_amount_open(self):
        for line in self:
            line.amount_open = abs(line.move_line_id.amount_residual_currency)

    @api.depends('netting_id.amount',
                 'netting_id.receivable_line_ids.amount_open',
                 'netting_id.payable_line_ids.amount_open')
    def _compute_amount_offset(self):
        allocations = {}
        for netting in self.netting_id:
            allocations.update(netting._allocate())
        for line in self:
            line.amount_offset = allocations.get(line, 0.0)
            line.amount_after = line.amount_open - line.amount_offset

    @api.constrains('move_line_id')
    def _check_move_line(self):
        for line in self:
            netting, ml = line.netting_id, line.move_line_id
            if ml.parent_state != 'posted':
                raise ValidationError(_(
                    'Journal item %(item)s is not posted.',
                    item=ml.display_name))
            if not ml.account_id.reconcile:
                raise ValidationError(_(
                    'Account %(account)s does not allow reconciliation, its '
                    'items cannot be offset.',
                    account=ml.account_id.display_name))
            if ml.partner_id.commercial_partner_id \
                    != netting.commercial_partner_id:
                raise ValidationError(_(
                    'Journal item %(item)s belongs to another partner.',
                    item=ml.display_name))
            if ml.currency_id != netting.currency_id:
                raise ValidationError(_(
                    'Journal item %(item)s is in %(item_currency)s, the '
                    'netting is in %(currency)s.',
                    item=ml.display_name,
                    item_currency=ml.currency_id.name,
                    currency=netting.currency_id.name))
