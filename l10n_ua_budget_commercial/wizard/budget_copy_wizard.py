"""Копіювання плану в інший сценарій та/або період з коефіцієнтом."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaBudgetCopyWizard(models.TransientModel):
    _name = 'l10n_ua.budget.copy.wizard'
    _description = 'Copy Budget'

    plan_id = fields.Many2one('l10n_ua.budget.plan', string='Budget', required=True, ondelete='cascade')
    name = fields.Char(string='New Budget Name', required=True)
    scenario = fields.Selection(
        [('base', 'Base'), ('optimistic', 'Optimistic'), ('pessimistic', 'Pessimistic')],
        string='Scenario', required=True,
    )
    shift_months = fields.Integer(
        string='Shift Period by (months)', default=0,
        help='12 copies the budget to the next year, 3 to the next quarter.',
    )
    coefficient = fields.Float(
        string='Coefficient, %', default=100.0,
        help='Planned amounts are multiplied by this percentage, e.g. 110 for +10%.',
    )
    copy_children = fields.Boolean(
        string='Copy Sub-budgets', default=True,
        help='Copy the whole hierarchy of sub-budgets (responsibility centres, projects).',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan = self.env['l10n_ua.budget.plan'].browse(
            res.get('plan_id') or self.env.context.get('active_id'))
        if plan:
            res.setdefault('plan_id', plan.id)
            res.setdefault('name', plan.name)
            res.setdefault('scenario', plan.scenario)
        return res

    @staticmethod
    def _shift_end(date_to, shift):
        """Зсув кінцевої дати; кінець місяця лишається кінцем місяця (28.02 → 31.03)."""
        is_month_end = (date_to + relativedelta(days=1)).day == 1
        shifted = date_to + shift
        return shifted + relativedelta(day=31) if is_month_end else shifted

    def _copy_plan(self, plan, parent=None, name=None):
        if self.shift_months % 12 and plan.period_type == 'year':
            raise UserError(_('A budget broken down by years can only be shifted by whole years.'))
        if self.shift_months % 3 and plan.period_type == 'quarter':
            raise UserError(_('A budget broken down by quarters can only be shifted by whole quarters.'))
        shift = relativedelta(months=self.shift_months)
        factor = self.coefficient / 100.0
        new_plan = plan.copy({
            'name': name or plan.name,
            'scenario': self.scenario,
            'date_from': plan.date_from + shift,
            'date_to': self._shift_end(plan.date_to, shift),
            'parent_id': parent.id if parent else plan.parent_id.id,
            'source_plan_id': plan.id,
            'line_ids': [(0, 0, {
                'item_id': line.item_id.id,
                'date_from': line.date_from + shift,
                'date_to': self._shift_end(line.date_to, shift),
                'analytic_account_id': line.analytic_account_id.id,
                'planned_amount': plan.currency_id.round(line.planned_amount * factor),
                'note': line.note,
            }) for line in plan.line_ids],
        })
        if self.copy_children:
            for child in plan.child_ids:
                self._copy_plan(child, parent=new_plan)
        return new_plan

    def action_copy(self):
        self.ensure_one()
        new_plan = self._copy_plan(self.plan_id, name=self.name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'l10n_ua.budget.plan',
            'res_id': new_plan.id,
            'view_mode': 'form',
        }
