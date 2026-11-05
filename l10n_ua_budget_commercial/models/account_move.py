"""Контроль бюджету при проведенні рахунків постачальників (вимкнено за замовчуванням)."""

from markupsafe import Markup, escape

from odoo import models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        posted._l10n_ua_check_budget()
        return posted

    def _l10n_ua_check_budget(self):
        BudgetLine = self.env['l10n_ua.budget.line'].sudo()
        for move in self:
            mode = move.company_id.l10n_ua_budget_control
            if mode == 'none' or not move.is_purchase_document(include_receipts=True):
                continue
            lines = BudgetLine._lines_for_move(move)
            if not lines:
                continue
            # Перерахунок факту вже з цим документом.
            lines._refresh_actuals()
            over = lines.filtered('is_over_budget')
            if not over:
                continue
            details = []
            for line in over:
                details.append(_(
                    '%(item)s (%(budget)s, %(from)s – %(to)s): planned %(planned)s, actual %(actual)s',
                    item=line.item_id.display_name, budget=line.plan_id.name,
                    planned=line.planned_amount, actual=line.actual_amount,
                    **{'from': line.date_from, 'to': line.date_to}))
            if mode == 'block':
                raise UserError(_('Posting %(move)s exceeds the approved budget:\n%(details)s',
                                  move=move.display_name, details='\n'.join(details)))
            move.message_post(body=Markup('%s<ul>%s</ul>') % (
                _('Budget exceeded:'),
                Markup().join(Markup('<li>%s</li>') % escape(d) for d in details),
            ))
