"""План бюджету (БДР або БДДС) на період з розбивкою на місяці/квартали/рік.

Ієрархія «компанія → ЦФВ → проєкт» будується через батьківський план:
план компанії має дочірні плани ЦФВ, ті — плани проєктів. ЦФВ або проєкт —
це аналітичний рахунок (будь-якого аналітичного плану), який за
замовчуванням переходить у рядки плану і фільтрує факт.
"""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


PERIOD_MONTHS = {'month': 1, 'quarter': 3, 'year': 12}


class L10nUaBudgetPlan(models.Model):
    _name = 'l10n_ua.budget.plan'
    _description = 'Budget Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _parent_name = 'parent_id'
    _parent_store = True
    _check_company_auto = True
    _order = 'date_from desc, name'

    name = fields.Char(string='Name', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    budget_type = fields.Selection(
        [('pnl', 'Income & Expense Budget (accrual)'),
         ('cash', 'Cash Flow Budget (cash basis)')],
        string='Budget Type', required=True, default='pnl', tracking=True,
    )
    scenario = fields.Selection(
        [('base', 'Base'), ('optimistic', 'Optimistic'), ('pessimistic', 'Pessimistic')],
        string='Scenario', required=True, default='base', tracking=True,
    )
    level = fields.Selection(
        [('company', 'Company'), ('center', 'Responsibility Centre'), ('project', 'Project')],
        string='Level', required=True, default='company',
    )
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    period_type = fields.Selection(
        [('month', 'Month'), ('quarter', 'Quarter'), ('year', 'Year')],
        string='Breakdown', required=True, default='month',
    )
    parent_id = fields.Many2one(
        'l10n_ua.budget.plan', string='Parent Budget', index=True, ondelete='restrict',
        check_company=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('l10n_ua.budget.plan', 'parent_id', string='Sub-budgets')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Responsibility Centre / Project',
        check_company=True,
        help='Analytic account of the responsibility centre (ЦФВ) or project. '
             'It is the default analytic of new lines and filters actuals.',
    )
    user_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user, tracking=True,
    )
    source_plan_id = fields.Many2one(
        'l10n_ua.budget.plan', string='Copied From', readonly=True, copy=False,
        ondelete='set null',
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('approved', 'Approved'), ('closed', 'Closed')],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    line_ids = fields.One2many('l10n_ua.budget.line', 'plan_id', string='Lines', copy=True)
    actuals_date = fields.Datetime(string='Actuals Updated On', readonly=True, copy=False)
    note = fields.Html(string='Notes')

    amount_planned = fields.Monetary(compute='_compute_amounts', string='Planned')
    amount_actual = fields.Monetary(compute='_compute_amounts', string='Actual')
    amount_remaining = fields.Monetary(compute='_compute_amounts', string='Remaining')
    execution_pct = fields.Float(compute='_compute_amounts', string='Execution, %')
    child_count = fields.Integer(compute='_compute_child_count', string='Sub-budget Count')

    _check_dates = models.Constraint(
        'CHECK(date_from <= date_to)',
        'The start date of a budget must be before its end date!',
    )

    @api.depends('line_ids.planned_amount', 'line_ids.actual_amount', 'line_ids.item_type')
    def _compute_amounts(self):
        for plan in self:
            # Сальдо «доходи − витрати»: для БДР — фінансовий результат,
            # для БДДС — чистий рух коштів.
            planned = actual = 0.0
            for line in plan.line_ids:
                sign = 1 if line.item_type == 'income' else -1
                planned += sign * line.planned_amount
                actual += sign * line.actual_amount
            plan.amount_planned = planned
            plan.amount_actual = actual
            plan.amount_remaining = planned - actual
            plan.execution_pct = (actual / planned * 100.0) if planned else 0.0

    @api.depends('child_ids')
    def _compute_child_count(self):
        for plan in self:
            plan.child_count = len(plan.child_ids)

    @api.constrains('parent_id')
    def _check_parent(self):
        if self._has_cycle():
            raise ValidationError(_('Budgets cannot be nested recursively.'))
        for plan in self.filtered('parent_id'):
            parent = plan.parent_id
            if parent.budget_type != plan.budget_type:
                raise ValidationError(_('A sub-budget must have the same budget type as its parent.'))
            if plan.date_from < parent.date_from or plan.date_to > parent.date_to:
                raise ValidationError(_('A sub-budget period must lie within the parent budget period.'))

    @api.constrains('date_from', 'date_to', 'period_type')
    def _check_period(self):
        for plan in self:
            if plan.date_from.day != 1:
                raise ValidationError(_('A budget must start on the first day of a month.'))
            months = PERIOD_MONTHS[plan.period_type]
            if plan.period_type != 'month' and (plan.date_from.month - 1) % months:
                raise ValidationError(_('A budget broken down by quarters or years must start '
                                        'at the beginning of a quarter or year.'))

    # ------------------------------------------------------------------
    # Періоди
    # ------------------------------------------------------------------

    def _get_buckets(self):
        """Список (date_from, date_to) періодів плану з урахуванням розбивки."""
        self.ensure_one()
        step = relativedelta(months=PERIOD_MONTHS[self.period_type])
        buckets = []
        start = self.date_from
        while start <= self.date_to:
            end = min(start + step - relativedelta(days=1), self.date_to)
            buckets.append((start, end))
            start += step
        return buckets

    def _bucket_label(self, date_from):
        self.ensure_one()
        if self.period_type == 'year':
            return str(date_from.year)
        if self.period_type == 'quarter':
            return f'{date_from.year}-Q{(date_from.month - 1) // 3 + 1}'
        return date_from.strftime('%Y-%m')

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------

    def _check_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise UserError(_('Only accounting administrators can approve, close or reopen budgets.'))

    def action_approve(self):
        self._check_manager()
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_('Only draft budgets can be approved.'))
            if not plan.line_ids:
                raise UserError(_('Budget "%s" has no lines.', plan.name))
        self.write({'state': 'approved'})
        self.action_refresh_actuals()

    def action_close(self):
        self._check_manager()
        if self.filtered(lambda p: p.state != 'approved'):
            raise UserError(_('Only approved budgets can be closed.'))
        # Закриття фіксує факт на дату закриття.
        self.action_refresh_actuals()
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self._check_manager()
        self.write({'state': 'draft'})

    def action_refresh_actuals(self):
        plans = self.filtered(lambda p: p.state != 'closed')
        plans.line_ids._refresh_actuals()
        plans.write({'actuals_date': fields.Datetime.now()})
        return True

    def action_generate_lines(self):
        """Порожні рядки: кожна стаття типу плану × кожен період.

        Існуючі рядки не чіпаються, тож дію можна повторити після додавання
        статей у довідник.
        """
        Item = self.env['l10n_ua.budget.item']
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_('Lines can only be generated in a draft budget.'))
            items = Item.search([
                ('budget_type', '=', plan.budget_type),
                ('child_ids', '=', False),
                ('company_id', 'in', [False, plan.company_id.id]),
            ])
            existing = {
                (line.item_id.id, line.date_from, line.analytic_account_id.id)
                for line in plan.line_ids
            }
            vals_list = []
            for item in items:
                for date_from, date_to in plan._get_buckets():
                    key = (item.id, date_from, plan.analytic_account_id.id)
                    if key in existing:
                        continue
                    vals_list.append({
                        'plan_id': plan.id,
                        'item_id': item.id,
                        'date_from': date_from,
                        'date_to': date_to,
                        'analytic_account_id': plan.analytic_account_id.id,
                    })
            self.env['l10n_ua.budget.line'].create(vals_list)
        return True

    def unlink(self):
        if self.filtered(lambda p: p.state != 'draft'):
            raise UserError(_('Only draft budgets can be deleted.'))
        return super().unlink()

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        for plan, vals in zip(self, vals_list):
            if 'name' not in (default or {}):
                vals['name'] = _('%s (copy)', plan.name)
        return vals_list

    # ------------------------------------------------------------------
    # Навігація
    # ------------------------------------------------------------------

    def action_open_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Budget Analysis'),
            'res_model': 'l10n_ua.budget.line',
            'view_mode': 'pivot,graph,list',
            'domain': [('plan_id', 'child_of', self.id)],
            'context': {'search_default_groupby_item': 1},
        }

    def action_open_children(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sub-budgets'),
            'res_model': 'l10n_ua.budget.plan',
            'view_mode': 'list,form',
            'domain': [('parent_id', '=', self.id)],
            'context': {
                'default_parent_id': self.id,
                'default_company_id': self.company_id.id,
                'default_budget_type': self.budget_type,
                'default_scenario': self.scenario,
                'default_date_from': self.date_from,
                'default_date_to': self.date_to,
                'default_period_type': self.period_type,
                'default_level': 'project' if self.level == 'center' else 'center',
            },
        }

    @api.model
    def _cron_refresh_actuals(self):
        # Cron працює для всіх компаній, тож правила доступу не мають обрізати плани.
        self.sudo().search([('state', '=', 'approved')]).action_refresh_actuals()
