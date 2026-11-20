from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


# Mapping: account code prefix → financial result account code
ACCOUNT_RESULT_MAP = {
    # Operating result → 791
    '70': '791', '71': '791',
    '90': '791', '92': '791', '93': '791', '94': '791',
    '80': '791', '81': '791', '82': '791', '83': '791', '84': '791',
    '98': '791',
    # Financial result → 792
    '72': '792', '73': '792',
    '95': '792', '96': '792',
    # Other result → 793
    '74': '793',
    '97': '793',
}

# Revenue account prefixes (class 7) — normally have credit balance
REVENUE_PREFIXES = ('70', '71', '72', '73', '74')

# Expense account prefixes (classes 8, 9) — normally have debit balance
EXPENSE_PREFIXES = ('80', '81', '82', '83', '84', '90', '92', '93', '94', '95', '96', '97', '98')


class L10nUaPeriodClosing(models.Model):
    _name = 'l10n_ua.period.closing'
    _description = 'Period Closing'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    period_id = fields.Many2one(
        'l10n_ua.tax.period',
        string='Period',
        required=True,
        tracking=True,
        domain="[('state', '=', 'open'), ('period_type', '=', 'month')]",
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    date = fields.Date(
        string='Closing Date',
        compute='_compute_date',
        store=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
    )
    closing_move_id = fields.Many2one(
        'account.move',
        string='Closing Entry',
        readonly=True,
        copy=False,
    )
    retained_move_id = fields.Many2one(
        'account.move',
        string='Retained Earnings Entry',
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('closed', 'Closed'),
            ('reversed', 'Reversed'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )
    lock_period = fields.Boolean(
        string='Lock Period',
        default=True,
        help='Set period lock date on company to prevent backdated entries',
    )
    note = fields.Text(string='Notes')

    # --- Config accounts (with smart defaults) ---
    account_791_id = fields.Many2one(
        'account.account',
        string='791 Результат операційної діяльності',
        domain="[]",
    )
    account_792_id = fields.Many2one(
        'account.account',
        string='792 Результат фінансових операцій',
        domain="[]",
    )
    account_793_id = fields.Many2one(
        'account.account',
        string='793 Результат іншої діяльності',
        domain="[]",
    )
    account_profit_id = fields.Many2one(
        'account.account',
        string='441 Нерозподілений прибуток',
        domain="[]",
    )
    account_loss_id = fields.Many2one(
        'account.account',
        string='442 Непокриті збитки',
        domain="[]",
    )

    # --- Computed summary ---
    total_revenue = fields.Monetary(
        string='Total Revenue',
        compute='_compute_summary',
        currency_field='currency_id',
    )
    total_expenses = fields.Monetary(
        string='Total Expenses',
        compute='_compute_summary',
        currency_field='currency_id',
    )
    net_result = fields.Monetary(
        string='Net Result',
        compute='_compute_summary',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
    )
    closing_line_ids = fields.One2many(
        'l10n_ua.period.closing.line',
        'closing_id',
        string='Closing Lines',
    )
    deferral_line_ids = fields.Many2many(
        'l10n_ua.deferral.line',
        string='Deferral Entries',
        compute='_compute_deferral_line_ids',
        help='Deferred expense/revenue (39/69) recognitions falling into the '
             'period. Closing the period posts the unposted ones before the '
             'P&L accounts are closed.',
    )

    def _default_journal(self):
        return self.env['account.journal'].search([
            ('code', '=', 'ZAK'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    @api.depends('period_id')
    def _compute_name(self):
        for rec in self:
            if rec.period_id:
                rec.name = f'Закриття {rec.period_id.name}'
            else:
                rec.name = 'Нове закриття'

    @api.depends('period_id.date_end')
    def _compute_date(self):
        for rec in self:
            rec.date = rec.period_id.date_end if rec.period_id else False

    @api.depends('closing_line_ids.balance', 'closing_line_ids.account_type')
    def _compute_summary(self):
        for rec in self:
            revenue = sum(
                line.balance for line in rec.closing_line_ids
                if line.account_type == 'revenue'
            )
            expenses = sum(
                line.balance for line in rec.closing_line_ids
                if line.account_type == 'expense'
            )
            rec.total_revenue = revenue
            rec.total_expenses = expenses
            rec.net_result = revenue - expenses

    @api.depends('period_id', 'company_id', 'state')
    def _compute_deferral_line_ids(self):
        for rec in self:
            if rec.period_id and rec.company_id:
                rec.deferral_line_ids = rec._get_due_deferral_lines(posted=None)
            else:
                rec.deferral_line_ids = False

    def _get_due_deferral_lines(self, posted=False):
        """Deferral schedule lines of this company dated inside the period.

        :param posted: False → only lines still waiting for an entry,
                       None → all lines of running/done schedules.
        """
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.period_id.date_start),
            ('date', '<=', self.period_id.date_end),
            ('deferral_id.state', 'in', ('running', 'done')),
        ]
        if posted is False:
            domain.append(('is_posted', '=', False))
        return self.env['l10n_ua.deferral.line'].search(domain)

    def _post_deferral_entries(self):
        """Recognise deferred expenses/revenue (39/69) of the period (#372).

        Runs before the P&L accounts are read so the recognised share lands in
        this period's financial result. Lines already posted (manually or by a
        previous closing) are skipped, so re-running is idempotent.
        """
        self.ensure_one()
        return self._get_due_deferral_lines()._post(closing=self)

    def _reverse_deferral_entries(self):
        """Reverse the recognitions this closing posted and free the lines."""
        self.ensure_one()
        lines = self.env['l10n_ua.deferral.line'].search([
            ('closing_id', '=', self.id),
        ])
        lines._unpost(date=self.date)

    @api.onchange('period_id', 'company_id')
    def _onchange_period_id(self):
        if self.period_id and self.company_id:
            self._set_default_accounts()

    def _set_default_accounts(self):
        Account = self.env['account.account']
        company = self.company_id
        for code, field in [
            ('791', 'account_791_id'),
            ('792', 'account_792_id'),
            ('793', 'account_793_id'),
            ('441', 'account_profit_id'),
            ('442', 'account_loss_id'),
        ]:
            if not self[field]:
                acc = Account.search([
                    ('code', '=like', code + '%'),
                    ('company_ids', 'in', company.id),
                ], limit=1)
                if acc:
                    self[field] = acc

    def _get_result_account(self, account_code):
        """Return the financial result account (79x) for a given P&L account code."""
        for prefix, result_code in ACCOUNT_RESULT_MAP.items():
            if account_code.startswith(prefix):
                if result_code == '791':
                    return self.account_791_id
                elif result_code == '792':
                    return self.account_792_id
                elif result_code == '793':
                    return self.account_793_id
        return False

    def _get_account_balances(self):
        """Get balances for all P&L accounts (classes 7, 8, 9) for the period."""
        self.ensure_one()
        period = self.period_id
        company = self.company_id

        # All P&L account prefixes
        all_prefixes = list(REVENUE_PREFIXES) + list(EXPENSE_PREFIXES)

        # Build domain for account.move.line
        domain = [
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
            ('company_id', '=', company.id),
            ('parent_state', '=', 'posted'),
        ]

        # Get all accounts in the P&L range
        Account = self.env['account.account']
        account_domain = []
        # Build OR domain for all prefixes
        prefix_domains = []
        for prefix in all_prefixes:
            prefix_domains.append(('code', '=like', prefix + '%'))
        if prefix_domains:
            # Combine with OR
            or_domain = ['|'] * (len(prefix_domains) - 1) + prefix_domains
            account_domain += or_domain

        accounts = Account.search(account_domain)
        if not accounts:
            return {}

        # Read balances from account.move.line
        MoveLine = self.env['account.move.line']
        results = {}
        for account in accounts:
            lines = MoveLine.search(domain + [('account_id', '=', account.id)])
            debit = sum(lines.mapped('debit'))
            credit = sum(lines.mapped('credit'))
            balance = debit - credit  # positive = debit balance, negative = credit balance

            if abs(balance) > 0.005:  # Skip zero balances
                is_revenue = any(account.code.startswith(p) for p in REVENUE_PREFIXES)
                results[account] = {
                    'debit': debit,
                    'credit': credit,
                    'balance': balance,
                    'type': 'revenue' if is_revenue else 'expense',
                }

        return results

    def action_compute(self):
        """Preview: compute account balances and show summary."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only compute in draft state.'))

        self._set_default_accounts()
        self._validate_accounts()

        # Clear old lines
        self.closing_line_ids.unlink()

        balances = self._get_account_balances()
        lines = []
        for account, data in balances.items():
            result_account = self._get_result_account(account.code)
            lines.append((0, 0, {
                'account_id': account.id,
                'account_type': data['type'],
                'debit': data['debit'],
                'credit': data['credit'],
                'balance': abs(data['balance']),
                'result_account_id': result_account.id if result_account else False,
            }))

        self.closing_line_ids = lines

    def _validate_accounts(self):
        """Validate that all required accounts are set."""
        missing = []
        if not self.account_791_id:
            missing.append('791')
        if not self.account_792_id:
            missing.append('792')
        if not self.account_793_id:
            missing.append('793')
        if not self.account_profit_id:
            missing.append('441')
        if not self.account_loss_id:
            missing.append('442')
        if missing:
            raise UserError(_(
                'Missing accounts: %s. Please configure them on the closing form.',
                ', '.join(missing)
            ))

    def action_close(self):
        """Generate closing entries and lock the period."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only close from draft state.'))

        if self.period_id.state != 'open':
            raise UserError(_('Period %s is not open.', self.period_id.name))

        # Check no other closing exists for this period
        existing = self.search([
            ('period_id', '=', self.period_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'closed'),
            ('id', '!=', self.id),
        ])
        if existing:
            raise UserError(_(
                'Period %s already has an active closing entry.',
                self.period_id.name,
            ))

        self._set_default_accounts()
        self._validate_accounts()

        # Step 0: recognise deferred expenses/revenue (39/69) of the month
        self._post_deferral_entries()

        # Recompute balances
        self.action_compute()

        if not self.closing_line_ids:
            raise UserError(_('No P&L account balances found for this period.'))

        # Step 1: Create closing journal entry (P&L accounts → 79x)
        closing_move = self._create_closing_move()
        closing_move.action_post()

        # Step 2: Create retained earnings entry (79x → 441/442)
        retained_move = self._create_retained_move()
        retained_move.action_post()

        # Step 3: Update state and lock
        vals = {
            'closing_move_id': closing_move.id,
            'retained_move_id': retained_move.id,
            'state': 'closed',
        }
        self.write(vals)

        # Lock period
        if self.lock_period:
            self.company_id.sudo().write({
                'period_lock_date': self.period_id.date_end,
            })

        # Close the tax period
        self.period_id.write({'state': 'closed'})

    def _create_closing_move(self):
        """Create the closing journal entry that zeroes P&L accounts."""
        self.ensure_one()
        move_lines = []

        for line in self.closing_line_ids:
            account = line.account_id
            result_account = line.result_account_id
            if not result_account:
                continue

            balance = line.debit - line.credit  # from move.lines: positive=debit, negative=credit

            if line.account_type == 'revenue':
                # Revenue accounts normally have credit balance (balance < 0)
                # To zero: debit the revenue account, credit the 79x account
                amount = abs(balance)
                move_lines.append((0, 0, {
                    'account_id': account.id,
                    'name': f'Закриття {account.code} {account.name}',
                    'debit': amount if balance < 0 else 0,
                    'credit': amount if balance > 0 else 0,
                }))
                move_lines.append((0, 0, {
                    'account_id': result_account.id,
                    'name': f'Закриття {account.code} → {result_account.code}',
                    'debit': amount if balance > 0 else 0,
                    'credit': amount if balance < 0 else 0,
                }))
            else:
                # Expense accounts normally have debit balance (balance > 0)
                # To zero: credit the expense account, debit the 79x account
                amount = abs(balance)
                move_lines.append((0, 0, {
                    'account_id': account.id,
                    'name': f'Закриття {account.code} {account.name}',
                    'debit': amount if balance < 0 else 0,
                    'credit': amount if balance > 0 else 0,
                }))
                move_lines.append((0, 0, {
                    'account_id': result_account.id,
                    'name': f'Закриття {account.code} → {result_account.code}',
                    'debit': amount if balance > 0 else 0,
                    'credit': amount if balance < 0 else 0,
                }))

        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': f'Закриття рахунків доходів/витрат {self.period_id.name}',
            'line_ids': move_lines,
        })
        return move

    def _create_retained_move(self):
        """Create the journal entry that transfers 79x balances to 441/442."""
        self.ensure_one()
        move_lines = []

        # Get balances of 79x accounts after the closing move was posted
        for result_account, label in [
            (self.account_791_id, 'операційної діяльності'),
            (self.account_792_id, 'фінансових операцій'),
            (self.account_793_id, 'іншої діяльності'),
        ]:
            if not result_account:
                continue

            # Calculate the balance of this 79x account for the period
            # After closing entry, 79x has accumulated result
            MoveLine = self.env['account.move.line']
            lines = MoveLine.search([
                ('account_id', '=', result_account.id),
                ('date', '>=', self.period_id.date_start),
                ('date', '<=', self.period_id.date_end),
                ('company_id', '=', self.company_id.id),
                ('parent_state', '=', 'posted'),
            ])
            balance = sum(lines.mapped('debit')) - sum(lines.mapped('credit'))

            if abs(balance) < 0.005:
                continue

            # Credit balance on 79x = profit → debit 79x, credit 441
            # Debit balance on 79x = loss → debit 442, credit 79x
            if balance < 0:
                # Credit balance = profit
                amount = abs(balance)
                move_lines.append((0, 0, {
                    'account_id': result_account.id,
                    'name': f'Результат {label} → нерозподілений прибуток',
                    'debit': amount,
                    'credit': 0,
                }))
                move_lines.append((0, 0, {
                    'account_id': self.account_profit_id.id,
                    'name': f'Нерозподілений прибуток ({label})',
                    'debit': 0,
                    'credit': amount,
                }))
            else:
                # Debit balance = loss
                amount = abs(balance)
                move_lines.append((0, 0, {
                    'account_id': self.account_loss_id.id,
                    'name': f'Непокриті збитки ({label})',
                    'debit': amount,
                    'credit': 0,
                }))
                move_lines.append((0, 0, {
                    'account_id': result_account.id,
                    'name': f'Результат {label} → непокриті збитки',
                    'debit': 0,
                    'credit': amount,
                }))

        if not move_lines:
            # Create a dummy zero move if nothing to transfer
            # (all 79x are zero — unlikely but possible)
            move_lines = [(0, 0, {
                'account_id': self.account_791_id.id,
                'name': 'Нульовий результат',
                'debit': 0,
                'credit': 0,
            })]

        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': f'Фінансовий результат → нерозподілений прибуток/збитки {self.period_id.name}',
            'line_ids': move_lines,
        })
        return move

    def action_reverse(self):
        """Reverse the closing and unlock the period."""
        self.ensure_one()
        if self.state != 'closed':
            raise UserError(_('Can only reverse a closed period.'))

        # Reverse the retained earnings move first, then the closing move
        if self.retained_move_id and self.retained_move_id.state == 'posted':
            self.retained_move_id._reverse_moves(
                default_values_list=[{
                    'date': self.date,
                    'ref': f'Сторно: {self.retained_move_id.ref}',
                }],
                cancel=True,
            )

        if self.closing_move_id and self.closing_move_id.state == 'posted':
            self.closing_move_id._reverse_moves(
                default_values_list=[{
                    'date': self.date,
                    'ref': f'Сторно: {self.closing_move_id.ref}',
                }],
                cancel=True,
            )

        # Reverse the deferral recognitions posted by this closing (#372)
        self._reverse_deferral_entries()

        # Reset lock date if we set it
        if self.lock_period:
            # Only reset if our date is the current lock date
            if self.company_id.period_lock_date == self.period_id.date_end:
                # Set to previous period end or False
                prev_period = self.env['l10n_ua.tax.period'].search([
                    ('date_end', '<', self.period_id.date_start),
                    ('company_id', '=', self.company_id.id),
                    ('state', '=', 'closed'),
                ], order='date_end desc', limit=1)
                new_lock_date = prev_period.date_end if prev_period else False
                self.company_id.sudo().write({
                    'period_lock_date': new_lock_date,
                })

        # Reopen period
        self.period_id.write({'state': 'open'})
        self.write({'state': 'reversed'})

    def action_draft(self):
        """Reset to draft (only from reversed)."""
        self.ensure_one()
        if self.state != 'reversed':
            raise UserError(_('Can only reset to draft from reversed state.'))
        self.write({
            'state': 'draft',
            'closing_move_id': False,
            'retained_move_id': False,
        })
        self.closing_line_ids.unlink()

    def action_open_currency_revaluation(self):
        """Відкрити переоцінку валютних коштів на дату закриття (#141).

        Регламентну операцію «Переоцінка валютних коштів» виконують перед
        закриттям місяця. Кнопка знаходить наявну переоцінку на цю дату або
        створює чернетку.
        """
        self.ensure_one()
        Reval = self.env['l10n_ua.currency.revaluation']
        reval = Reval.search([
            ('company_id', '=', self.company_id.id),
            ('date', '=', self.date),
        ], limit=1) or Reval.create({
            'company_id': self.company_id.id,
            'date': self.date,
            'journal_id': self.journal_id.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Переоцінка валюти'),
            'res_model': 'l10n_ua.currency.revaluation',
            'res_id': reval.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.constrains('period_id', 'company_id')
    def _check_unique_closing(self):
        for rec in self:
            if rec.state == 'closed':
                existing = self.search([
                    ('period_id', '=', rec.period_id.id),
                    ('company_id', '=', rec.company_id.id),
                    ('state', '=', 'closed'),
                    ('id', '!=', rec.id),
                ])
                if existing:
                    raise ValidationError(_(
                        'Only one active closing per period is allowed.'
                    ))


class L10nUaPeriodClosingLine(models.Model):
    _name = 'l10n_ua.period.closing.line'
    _description = 'Period Closing Line'
    _order = 'account_id'

    closing_id = fields.Many2one(
        'l10n_ua.period.closing',
        string='Closing',
        required=True,
        ondelete='cascade',
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
    )
    account_code = fields.Char(
        related='account_id.code',
        string='Code',
    )
    account_type = fields.Selection(
        selection=[
            ('revenue', 'Revenue'),
            ('expense', 'Expense'),
        ],
        string='Type',
    )
    debit = fields.Monetary(
        string='Debit',
        currency_field='currency_id',
    )
    credit = fields.Monetary(
        string='Credit',
        currency_field='currency_id',
    )
    balance = fields.Monetary(
        string='Balance',
        currency_field='currency_id',
    )
    result_account_id = fields.Many2one(
        'account.account',
        string='Closes to',
    )
    currency_id = fields.Many2one(
        related='closing_id.currency_id',
    )
