"""Рядок бюджету: стаття × період × (ЦФВ/проєкт) × планова сума + факт.

Факт зберігається (``actual_amount``), щоб зведена таблиця й графік могли
його агрегувати. Оновлюється кнопкою на плані, щоденним cron-ом для
затверджених планів і контролем бюджету при проведенні рахунків
постачальників.
"""

from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain


# Поля, що визначають план. Після затвердження їх змінювати не можна; факт
# оновлюється й далі.
PLAN_FIELDS = {'plan_id', 'item_id', 'date_from', 'date_to', 'analytic_account_id', 'planned_amount'}


class L10nUaBudgetLine(models.Model):
    _name = 'l10n_ua.budget.line'
    _description = 'Budget Line'
    _check_company_auto = True
    _order = 'plan_id, item_sequence, item_id, date_from'

    plan_id = fields.Many2one(
        'l10n_ua.budget.plan', string='Budget', required=True, ondelete='cascade', index=True,
    )
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='plan_id.currency_id')
    budget_type = fields.Selection(related='plan_id.budget_type', store=True)
    scenario = fields.Selection(related='plan_id.scenario', store=True)
    plan_state = fields.Selection(related='plan_id.state', string='Budget Status', store=True)
    item_id = fields.Many2one(
        'l10n_ua.budget.item', string='Budget Item', required=True, index=True,
        ondelete='restrict',
        domain="[('budget_type', '=', budget_type), ('company_id', 'in', [False, company_id])]",
    )
    item_type = fields.Selection(related='item_id.item_type', store=True)
    item_sequence = fields.Integer(related='item_id.sequence', store=True)
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', index=True,
        check_company=True,
        help='Responsibility centre or project. When set, only journal items '
             'distributed to it count, weighted by the distribution percentage.',
    )
    planned_amount = fields.Monetary(string='Planned', default=0.0)
    actual_amount = fields.Monetary(string='Actual', readonly=True, default=0.0, copy=False)
    variance_amount = fields.Monetary(
        string='Deviation', compute='_compute_variance', store=True,
        help='Actual minus planned.',
    )
    remaining_amount = fields.Monetary(
        string='Remaining', compute='_compute_variance', store=True,
        help='Planned minus actual.',
    )
    execution_pct = fields.Float(
        string='Execution, %', compute='_compute_variance', store=True, aggregator=False,
        digits=(16, 1),
    )
    is_over_budget = fields.Boolean(compute='_compute_variance', store=True, string='Over Budget')
    note = fields.Char(string='Comment')

    @api.depends('planned_amount', 'actual_amount', 'item_type')
    def _compute_variance(self):
        for line in self:
            line.variance_amount = line.actual_amount - line.planned_amount
            line.remaining_amount = line.planned_amount - line.actual_amount
            line.execution_pct = (line.actual_amount / line.planned_amount * 100.0) \
                if line.planned_amount else 0.0
            # Перевищення має сенс лише для витрат: перевиконання доходів — не порушення.
            line.is_over_budget = (
                line.item_type == 'expense'
                and line.currency_id.compare_amounts(line.actual_amount, line.planned_amount) > 0
            )

    @api.constrains('date_from', 'date_to', 'plan_id')
    def _check_dates(self):
        for line in self:
            if line.date_from > line.date_to:
                raise ValidationError(_('The start date of a budget line must be before its end date.'))
            plan = line.plan_id
            if line.date_from < plan.date_from or line.date_to > plan.date_to:
                raise ValidationError(_(
                    'Line "%(item)s" (%(from)s – %(to)s) is outside the budget period.',
                    item=line.item_id.display_name, **{'from': line.date_from, 'to': line.date_to}))

    @api.constrains('item_id', 'plan_id')
    def _check_item_type(self):
        for line in self:
            if line.item_id.budget_type != line.plan_id.budget_type:
                raise ValidationError(_(
                    'Item "%(item)s" does not belong to the budget type of "%(plan)s".',
                    item=line.item_id.display_name, plan=line.plan_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        plans = self.env['l10n_ua.budget.plan'].browse({v.get('plan_id') for v in vals_list if v.get('plan_id')})
        if plans.filtered(lambda p: p.state != 'draft'):
            raise UserError(_('Lines can only be added to a draft budget.'))
        for vals in vals_list:
            plan = plans.filtered(lambda p: p.id == vals.get('plan_id'))
            if plan and 'analytic_account_id' not in vals and plan.analytic_account_id:
                vals['analytic_account_id'] = plan.analytic_account_id.id
        return super().create(vals_list)

    def write(self, vals):
        if PLAN_FIELDS & set(vals) and self.filtered(lambda l: l.plan_id.state != 'draft'):
            raise UserError(_('Planned figures of an approved or closed budget cannot be changed. '
                              'Reset the budget to draft first.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda l: l.plan_id.state != 'draft'):
            raise UserError(_('Lines of an approved or closed budget cannot be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Факт
    # ------------------------------------------------------------------

    @api.model
    def _get_liquidity_accounts(self, company):
        """Грошові рахунки компанії: каса/банк і рахунки «гроші в дорозі».

        Платежі Odoo можуть проводитися через рахунки неоплачених надходжень/
        платежів журналу (outstanding), а не одразу на 311, тому вони теж
        вважаються грошовим боком.
        """
        accounts = self.env['account.account'].search([
            ('account_type', '=', 'asset_cash'),
            ('company_ids', 'in', company.id),
        ])
        journals = self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash', 'credit')),
            ('company_id', '=', company.id),
        ])
        accounts |= journals.default_account_id
        method_lines = journals.inbound_payment_method_line_ids | journals.outbound_payment_method_line_ids
        accounts |= method_lines.payment_account_id
        return accounts

    def _get_actual_domain(self, accounts, liquidity=None):
        self.ensure_one()
        domain = Domain([
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('account_id', 'in', accounts.ids),
        ])
        if self.budget_type == 'cash':
            domain &= Domain([
                ('account_id', 'not in', liquidity.ids),
                ('move_id.line_ids.account_id', 'in', liquidity.ids),
                ('credit' if self.item_type == 'income' else 'debit', '>', 0),
            ])
        item_analytics = self.item_id._get_analytic_filter()
        if item_analytics:
            domain &= Domain('analytic_distribution', 'in', item_analytics.ids)
        if self.analytic_account_id:
            domain &= Domain('analytic_distribution', 'in', self.analytic_account_id.ids)
        return domain

    def _line_amount(self, aml):
        """Сума проводки в напрямі статті (дохід/надходження додатні)."""
        if self.item_type == 'income':
            return -aml.balance
        return aml.balance

    @staticmethod
    def _analytic_share(distribution, analytic_id):
        """Частка (0..1) проводки, розподілена на аналітичний рахунок.

        Ключі ``analytic_distribution`` — id або «id1,id2» для кількох планів.
        """
        share = 0.0
        key = str(analytic_id)
        for ids, pct in (distribution or {}).items():
            if key in str(ids).split(','):
                share += pct
        return share / 100.0

    def _refresh_actuals(self):
        AML = self.env['account.move.line'].sudo()
        accounts_cache = {}
        liquidity_cache = {}
        for line in self:
            company = line.company_id
            key = (line.item_id.id, company.id)
            if key not in accounts_cache:
                accounts_cache[key] = line.item_id._get_accounts(company)
            accounts = accounts_cache[key]
            if not accounts:
                line.actual_amount = 0.0
                continue
            liquidity = None
            if line.budget_type == 'cash':
                if company.id not in liquidity_cache:
                    liquidity_cache[company.id] = self._get_liquidity_accounts(company)
                liquidity = liquidity_cache[company.id]
            domain = line._get_actual_domain(accounts, liquidity)
            if line.analytic_account_id:
                total = sum(
                    line._line_amount(aml) * self._analytic_share(aml.analytic_distribution, line.analytic_account_id.id)
                    for aml in AML.search(domain)
                )
            else:
                [(balance,)] = AML._read_group(domain, aggregates=['balance:sum'])
                balance = balance or 0.0
                total = -balance if line.item_type == 'income' else balance
            line.actual_amount = company.currency_id.round(total)

    @api.model
    def _lines_for_move(self, move):
        """Затверджені рядки БДР-витрат, які зачіпає проведений документ."""
        lines = self.search([
            ('company_id', '=', move.company_id.id),
            ('plan_state', '=', 'approved'),
            ('budget_type', '=', 'pnl'),
            ('item_type', '=', 'expense'),
            ('date_from', '<=', move.date),
            ('date_to', '>=', move.date),
        ])
        move_lines = move.line_ids.filtered(lambda l: l.display_type == 'product')
        accounts_cache = defaultdict(lambda: None)
        result = self.browse()
        for line in lines:
            if accounts_cache[line.item_id.id] is None:
                accounts_cache[line.item_id.id] = line.item_id._get_accounts(move.company_id)
            touched = move_lines.filtered(lambda l: l.account_id in accounts_cache[line.item_id.id])
            if line.analytic_account_id:
                touched = touched.filtered(
                    lambda l: self._analytic_share(l.analytic_distribution, line.analytic_account_id.id))
            if touched:
                result |= line
        return result

    def action_open_journal_items(self):
        """Проводки, з яких складається факт рядка."""
        self.ensure_one()
        accounts = self.item_id._get_accounts(self.company_id)
        liquidity = self._get_liquidity_accounts(self.company_id) if self.budget_type == 'cash' else None
        return {
            'type': 'ir.actions.act_window',
            'name': _('Actual: %s', self.item_id.display_name),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': list(self._get_actual_domain(accounts, liquidity)) if accounts else [('id', '=', 0)],
            'context': {'create': False},
        }
