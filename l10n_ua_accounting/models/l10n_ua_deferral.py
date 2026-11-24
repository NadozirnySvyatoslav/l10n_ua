"""Витрати і доходи майбутніх періодів (рахунки 39 / 69) — issue #372.

Odoo 19 Community не має відкладених доходів/витрат, тому графік розподілу
ведемо власною моделлю ``l10n_ua.deferral``:

* витрати майбутніх періодів (39): щомісячно Дт рахунок витрат / Кт 39;
* доходи майбутніх періодів (69): щомісячно Дт 69 / Кт рахунок доходів.

Графік (рядки ``l10n_ua.deferral.line``) будується рівними частками по
місяцях або пропорційно дням; копійки округлення забирає останній рядок, тож
сума графіка завжди дорівнює загальній сумі.

Проводки за місяць формує закриття періоду (``l10n_ua.period.closing``) —
до того, як рахунки доходів/витрат закриваються на 79x, тож списана частка
потрапляє у фінрезультат того самого місяця. Повторне закриття нічого не
дублює (рядок з проведеною проводкою пропускається), сторно закриття
сторнує й ці проводки. Для тих, хто не користується закриттям, є дія
«Провести до дати» і (вимкнений за замовчуванням) cron.
"""

import calendar
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


DEFERRAL_KINDS = [
    ('expense', 'Deferred Expense (39)'),
    ('revenue', 'Deferred Revenue (69)'),
]


def _month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


class L10nUaDeferral(models.Model):
    _name = 'l10n_ua.deferral'
    _description = 'Deferred Expense / Revenue Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']
    _order = 'date_start desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='/',
    )
    description = fields.Char(
        string='Description',
        tracking=True,
        help='What is being deferred: insurance, licence, rent paid in advance, '
             'subscription received in advance, etc.',
    )
    kind = fields.Selection(
        selection=DEFERRAL_KINDS,
        string='Type',
        required=True,
        default='expense',
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        tracking=True,
    )
    source_move_line_id = fields.Many2one(
        'account.move.line',
        string='Source Journal Item',
        readonly=True,
        copy=False,
        index='btree_not_null',
        check_company=True,
        help='Vendor bill / customer invoice line the schedule was created from.',
    )
    source_move_id = fields.Many2one(
        related='source_move_line_id.move_id',
        string='Source Document',
        store=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        check_company=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self._default_journal(),
    )
    deferral_account_id = fields.Many2one(
        'account.account',
        string='Deferral Account',
        required=True,
        check_company=True,
        tracking=True,
        help='Balance-sheet account holding the deferred amount: '
             '39 «Deferred expenses» or 69 «Deferred income».',
    )
    target_account_id = fields.Many2one(
        'account.account',
        string='Expense / Revenue Account',
        required=True,
        check_company=True,
        tracking=True,
        help='Account the amount is recognised to month by month '
             '(e.g. 92, 93, 949 for expenses; 703, 719 for revenue).',
    )
    amount_total = fields.Monetary(
        string='Total Amount',
        required=True,
        currency_field='currency_id',
        tracking=True,
    )
    date_start = fields.Date(
        string='Start Date',
        required=True,
        tracking=True,
    )
    date_end = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )
    method = fields.Selection(
        selection=[
            ('month', 'Equal monthly amounts'),
            ('day', 'Prorata by days'),
        ],
        string='Method',
        required=True,
        default='month',
        tracking=True,
        help='Equal monthly amounts: the total is split evenly over every '
             'calendar month touched by the period.\n'
             'Prorata by days: each month gets a share proportional to the '
             'number of days of the period falling into it.\n'
             'In both cases the last month absorbs the rounding difference.',
    )
    line_ids = fields.One2many(
        'l10n_ua.deferral.line',
        'deferral_id',
        string='Schedule',
        copy=False,
    )
    initial_move_id = fields.Many2one(
        'account.move',
        string='Reclassification Entry',
        readonly=True,
        copy=False,
        help='Entry moving the amount from the expense/revenue account of the '
             'source document to the deferral account (39/69). Created only '
             'when the source line was not booked on the deferral account.',
    )
    amount_posted = fields.Monetary(
        string='Recognised',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    amount_residual = fields.Monetary(
        string='Remaining Balance',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    amount_scheduled = fields.Monetary(
        string='Scheduled',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    note = fields.Text(string='Notes')

    _check_amount_positive = models.Constraint(
        'CHECK(amount_total > 0)',
        'The deferred amount must be positive.',
    )
    _check_dates = models.Constraint(
        'CHECK(date_end >= date_start)',
        'The end date must not be earlier than the start date.',
    )

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------
    def _default_journal(self):
        company = self.env.company
        return company.l10n_ua_deferral_journal_id or self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', company.id),
        ], limit=1)

    @api.model
    def _get_default_deferral_account(self, kind, company):
        """39 for expenses, 69 for revenue: company setting, else by code."""
        field = ('l10n_ua_deferred_expense_account_id' if kind == 'expense'
                 else 'l10n_ua_deferred_revenue_account_id')
        account = company[field]
        if account:
            return account
        prefix = '39' if kind == 'expense' else '69'
        return self.env['account.account'].search([
            ('code', '=like', prefix + '%'),
            ('company_ids', 'in', company.id),
            ('active', '=', True),
        ], order='code', limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                vals['name'] = self.env['ir.sequence'].with_company(
                    company).next_by_code('l10n_ua.deferral') or '/'
            if not vals.get('deferral_account_id') and vals.get('kind', 'expense'):
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                account = self._get_default_deferral_account(
                    vals.get('kind', 'expense'), company)
                if account:
                    vals['deferral_account_id'] = account.id
        return super().create(vals_list)

    @api.onchange('kind', 'company_id')
    def _onchange_kind(self):
        if self.company_id and self.kind:
            account = self._get_default_deferral_account(self.kind, self.company_id)
            if account:
                self.deferral_account_id = account

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('amount_total', 'line_ids.amount', 'line_ids.is_posted')
    def _compute_amounts(self):
        for rec in self:
            posted = sum(rec.line_ids.filtered('is_posted').mapped('amount'))
            rec.amount_posted = posted
            rec.amount_scheduled = sum(rec.line_ids.mapped('amount'))
            rec.amount_residual = rec.amount_total - posted

    @api.constrains('deferral_account_id', 'target_account_id')
    def _check_accounts(self):
        for rec in self:
            if rec.deferral_account_id == rec.target_account_id:
                raise ValidationError(_(
                    'The deferral account and the expense/revenue account '
                    'must be different.'))

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    def _get_schedule_months(self):
        """List of (month_first_day, month_last_day, days_in_period)."""
        self.ensure_one()
        months = []
        current = self.date_start.replace(day=1)
        while current <= self.date_end:
            last = _month_end(current)
            seg_start = max(current, self.date_start)
            seg_end = min(last, self.date_end)
            months.append((current, last, (seg_end - seg_start).days + 1))
            current += relativedelta(months=1)
        return months

    def _compute_schedule_amounts(self):
        """Return [(date, amount)]; amounts sum exactly to ``amount_total``."""
        self.ensure_one()
        currency = self.currency_id
        months = self._get_schedule_months()
        total = currency.round(self.amount_total)
        count = len(months)
        result = []
        if self.method == 'day':
            total_days = sum(m[2] for m in months)
            cumulative_days = 0
            allocated = 0.0
            for index, (_first, last, days) in enumerate(months):
                cumulative_days += days
                if index == count - 1:
                    amount = total - allocated
                else:
                    target = currency.round(total * cumulative_days / total_days)
                    amount = target - allocated
                amount = currency.round(amount)
                allocated = currency.round(allocated + amount)
                result.append((last, amount))
        else:
            per_month = currency.round(total / count)
            for index, (_first, last, _days) in enumerate(months):
                if index == count - 1:
                    amount = currency.round(total - per_month * (count - 1))
                else:
                    amount = per_month
                result.append((last, amount))
        return result

    def action_compute_schedule(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('The schedule can only be recomputed in draft.'))
            rec.line_ids.unlink()
            rec.write({
                'line_ids': [
                    (0, 0, {'date': line_date, 'amount': amount})
                    for line_date, amount in rec._compute_schedule_amounts()
                ],
            })
        return True

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm(self):
        """Lock the schedule, post the reclassification entry if needed."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft schedules can be started.'))
            if not rec.line_ids:
                rec.action_compute_schedule()
            if rec.currency_id.compare_amounts(
                    sum(rec.line_ids.mapped('amount')), rec.amount_total):
                raise UserError(_(
                    'The schedule of %(name)s does not add up to the total '
                    'amount. Recompute it before starting.', name=rec.name))
            if rec._needs_initial_move():
                move = self.env['account.move'].create(rec._prepare_initial_move_vals())
                move.action_post()
                rec.initial_move_id = move
            rec.state = 'running'
        return True

    def _needs_initial_move(self):
        self.ensure_one()
        line = self.source_move_line_id
        return bool(line) and line.account_id != self.deferral_account_id \
            and not self.initial_move_id

    def _prepare_initial_move_vals(self):
        """Dt 39 / Ct expense (expense) or Dt revenue / Ct 69 (revenue)."""
        self.ensure_one()
        source = self.source_move_line_id
        label = _('Deferral %(name)s: %(desc)s', name=self.name,
                  desc=self.description or source.name or '')
        amount = self.amount_total
        if self.kind == 'expense':
            debit_account, credit_account = self.deferral_account_id, source.account_id
        else:
            debit_account, credit_account = source.account_id, self.deferral_account_id
        return {
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': source.date,
            'ref': label,
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {
                    'name': label,
                    'account_id': debit_account.id,
                    'partner_id': self.partner_id.id,
                    'debit': amount,
                    'credit': 0.0,
                    'analytic_distribution': (
                        self.analytic_distribution if debit_account == source.account_id
                        else False),
                }),
                (0, 0, {
                    'name': label,
                    'account_id': credit_account.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': amount,
                    'analytic_distribution': (
                        self.analytic_distribution if credit_account == source.account_id
                        else False),
                }),
            ],
        }

    def action_cancel(self):
        for rec in self:
            if rec.line_ids.filtered('is_posted'):
                raise UserError(_(
                    'Schedule %(name)s already has posted entries. Reverse '
                    'them (or the period closing that posted them) first.',
                    name=rec.name))
            if rec.initial_move_id and rec.initial_move_id.state == 'posted':
                rec.initial_move_id._reverse_moves(
                    default_values_list=[{
                        'date': rec.initial_move_id.date,
                        'ref': _('Reversal of: %s', rec.initial_move_id.ref),
                    }],
                    cancel=True,
                )
            rec.write({'state': 'cancelled', 'initial_move_id': False})
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled schedules can be reset to draft.'))
            rec.state = 'draft'
        return True

    def action_post_due(self, date_to=None):
        """Post every unposted schedule line dated on or before ``date_to``."""
        date_to = fields.Date.to_date(date_to) or fields.Date.context_today(self)
        lines = self.line_ids.filtered(
            lambda l: l.deferral_id.state == 'running'
            and not l.is_posted and l.date <= date_to)
        lines._post()
        return True

    def _update_state_from_lines(self):
        for rec in self:
            if rec.state == 'running' and rec.line_ids \
                    and all(rec.line_ids.mapped('is_posted')):
                rec.state = 'done'
            elif rec.state == 'done' and not all(rec.line_ids.mapped('is_posted')):
                rec.state = 'running'

    @api.model
    def _cron_post_due(self):
        """Optional automation for companies that do not run period closing."""
        today = fields.Date.context_today(self)
        lines = self.env['l10n_ua.deferral.line'].search([
            ('deferral_id.state', '=', 'running'),
            ('move_id', '=', False),
            ('date', '<=', today),
        ])
        lines._post()

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled'):
                raise UserError(_(
                    'Only draft or cancelled schedules can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def action_open_moves(self):
        self.ensure_one()
        moves = self.line_ids.move_id | self.initial_move_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entries'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', moves.ids)],
        }


class L10nUaDeferralLine(models.Model):
    _name = 'l10n_ua.deferral.line'
    _description = 'Deferral Schedule Line'
    _order = 'deferral_id, date, id'

    deferral_id = fields.Many2one(
        'l10n_ua.deferral',
        string='Schedule',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='deferral_id.company_id', store=True)
    currency_id = fields.Many2one(related='deferral_id.currency_id')
    date = fields.Date(string='Date', required=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
        index='btree_not_null',
    )
    closing_id = fields.Many2one(
        'l10n_ua.period.closing',
        string='Posted by Closing',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help='Period closing that generated this entry; reversing that closing '
             'reverses the entry too.',
    )
    is_posted = fields.Boolean(
        string='Posted',
        compute='_compute_is_posted',
        store=True,
    )

    @api.depends('move_id.state')
    def _compute_is_posted(self):
        for line in self:
            line.is_posted = line.move_id.state == 'posted'

    def _prepare_move_vals(self):
        self.ensure_one()
        deferral = self.deferral_id
        label = _('%(name)s: recognition for %(month)s',
                  name=deferral.description or deferral.name,
                  month=self.date.strftime('%m.%Y'))
        amount = self.amount
        if deferral.kind == 'expense':
            debit_account = deferral.target_account_id
            credit_account = deferral.deferral_account_id
        else:
            debit_account = deferral.deferral_account_id
            credit_account = deferral.target_account_id
        target = deferral.target_account_id
        return {
            'move_type': 'entry',
            'journal_id': deferral.journal_id.id,
            'date': self.date,
            'ref': f'{deferral.name} — {label}',
            'company_id': deferral.company_id.id,
            'line_ids': [
                (0, 0, {
                    'name': label,
                    'account_id': debit_account.id,
                    'partner_id': deferral.partner_id.id,
                    'debit': amount,
                    'credit': 0.0,
                    'analytic_distribution': (
                        deferral.analytic_distribution if debit_account == target else False),
                }),
                (0, 0, {
                    'name': label,
                    'account_id': credit_account.id,
                    'partner_id': deferral.partner_id.id,
                    'debit': 0.0,
                    'credit': amount,
                    'analytic_distribution': (
                        deferral.analytic_distribution if credit_account == target else False),
                }),
            ],
        }

    def _post(self, closing=None):
        """Create and post the recognition entry. Idempotent per line."""
        to_post = self.filtered(
            lambda l: not l.is_posted
            and l.deferral_id.state == 'running'
            and not l.currency_id.is_zero(l.amount))
        if not to_post:
            return self.env['account.move']
        # Drop drafts left from a manual reset so they cannot be posted twice.
        stale = to_post.move_id.filtered(lambda m: m.state == 'draft')
        if stale:
            stale.unlink()
        moves = self.env['account.move'].create(
            [line._prepare_move_vals() for line in to_post])
        moves.action_post()
        for line, move in zip(to_post, moves):
            line.write({
                'move_id': move.id,
                'closing_id': closing.id if closing else False,
            })
        # Zero lines (possible with tiny totals) are complete by definition.
        to_post.deferral_id._update_state_from_lines()
        return moves

    def _unpost(self, date=None):
        """Reverse the recognition entries and free the lines for re-posting."""
        posted = self.filtered('is_posted')
        for line in posted:
            line.move_id._reverse_moves(
                default_values_list=[{
                    'date': date or line.move_id.date,
                    'ref': _('Reversal of: %s', line.move_id.ref),
                }],
                cancel=True,
            )
        self.write({'move_id': False, 'closing_id': False})
        self.deferral_id._update_state_from_lines()

    def action_post(self):
        """Post a single line manually (button in the schedule)."""
        self._post()
        return True


class L10nUaDeferralPostWizard(models.TransientModel):
    _name = 'l10n_ua.deferral.post.wizard'
    _description = 'Post Due Deferral Entries'

    date = fields.Date(
        string='Post Up To',
        required=True,
        default=lambda self: _month_end(fields.Date.context_today(self)),
    )
    deferral_ids = fields.Many2many(
        'l10n_ua.deferral',
        string='Schedules',
        help='Leave empty to post all running schedules of the current company.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'l10n_ua.deferral' \
                and 'deferral_ids' in fields_list:
            res['deferral_ids'] = [(6, 0, self.env.context.get('active_ids', []))]
        return res

    def action_post(self):
        self.ensure_one()
        deferrals = self.deferral_ids or self.env['l10n_ua.deferral'].search([
            ('state', '=', 'running'),
            ('company_id', 'in', self.env.companies.ids),
        ])
        deferrals.action_post_due(self.date)
        return {'type': 'ir.actions.act_window_close'}


class L10nUaDeferralBalanceWizard(models.TransientModel):
    _name = 'l10n_ua.deferral.balance.wizard'
    _description = 'Deferral Balances As Of Date'

    date = fields.Date(
        string='As of',
        required=True,
        default=fields.Date.context_today,
    )

    def action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Deferral balances as of %s', self.date.strftime('%d.%m.%Y')),
            'res_model': 'l10n_ua.deferral.report',
            'view_mode': 'pivot,list',
            'domain': [('date', '<=', self.date)],
            'context': {
                'search_default_groupby_kind': 1,
                'search_default_groupby_deferral': 1,
            },
        }


class L10nUaDeferralReport(models.Model):
    """Movements on 39/69 per schedule; summing rows up to a date gives the balance.

    One "deferred" row per started schedule (the amount put on 39/69) and one
    "recognised" row (negative) per posted monthly entry.
    """
    _name = 'l10n_ua.deferral.report'
    _description = 'Deferral Balances Analysis'
    _auto = False
    _order = 'date, deferral_id'

    deferral_id = fields.Many2one('l10n_ua.deferral', string='Schedule', readonly=True)
    kind = fields.Selection(DEFERRAL_KINDS, string='Type', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', readonly=True)
    deferral_account_id = fields.Many2one(
        'account.account', string='Deferral Account', readonly=True)
    target_account_id = fields.Many2one(
        'account.account', string='Expense / Revenue Account', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    movement = fields.Selection(
        [('deferred', 'Deferred'), ('recognised', 'Recognised')],
        string='Movement', readonly=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    amount = fields.Monetary(string='Balance Change', readonly=True,
                             currency_field='currency_id')

    def init(self):
        self.env.cr.execute(f"DROP VIEW IF EXISTS {self._table}")
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT row_number() OVER (ORDER BY src.date, src.deferral_id, src.movement)
                           AS id,
                       src.*
                  FROM (
                    SELECT d.id AS deferral_id,
                           d.kind,
                           d.company_id,
                           c.currency_id,
                           d.partner_id,
                           d.deferral_account_id,
                           d.target_account_id,
                           COALESCE(im.date, d.date_start) AS date,
                           'deferred' AS movement,
                           d.initial_move_id AS move_id,
                           d.amount_total AS amount
                      FROM l10n_ua_deferral d
                      JOIN res_company c ON c.id = d.company_id
                 LEFT JOIN account_move im ON im.id = d.initial_move_id
                     WHERE d.state IN ('running', 'done')
                    UNION ALL
                    SELECT d.id,
                           d.kind,
                           d.company_id,
                           c.currency_id,
                           d.partner_id,
                           d.deferral_account_id,
                           d.target_account_id,
                           m.date,
                           'recognised',
                           m.id,
                           -l.amount
                      FROM l10n_ua_deferral_line l
                      JOIN l10n_ua_deferral d ON d.id = l.deferral_id
                      JOIN res_company c ON c.id = d.company_id
                      JOIN account_move m ON m.id = l.move_id AND m.state = 'posted'
                     WHERE d.state IN ('running', 'done')
                  ) src
            )
        """)
