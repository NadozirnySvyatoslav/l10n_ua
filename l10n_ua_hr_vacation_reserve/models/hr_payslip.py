"""Hook на нарахування відпускних — обернена проводка Дт 471 / Кт 661."""

from odoo import _, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    vacation_reserve_reversal_move_id = fields.Many2one(
        'account.move',
        string='Проводка реверсу резерву',
        readonly=True,
        copy=False,
        help='Обернена проводка Дт 471 / Кт 661 на суму нарахованих відпускних',
    )

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for payslip in self:
            payslip._create_vacation_reserve_reversal()
        return res

    def action_payslip_cancel(self):
        # Cancel the reversal move first if it exists
        for payslip in self:
            move = payslip.vacation_reserve_reversal_move_id
            if move:
                if move.state == 'posted':
                    move.button_draft()
                move.button_cancel()
        return super().action_payslip_cancel()

    def _get_vacation_accrual_amount(self):
        """Сума нарахованих відпускних у поточному payslip."""
        self.ensure_one()
        if not hasattr(self, 'accrual_ids'):
            return 0.0
        vacation_accruals = self.accrual_ids.filtered(
            lambda a: a.accrual_type_id.category == 'vacation'
        )
        return sum(vacation_accruals.mapped('amount'))

    def _create_vacation_reserve_reversal(self):
        """Створити обернену проводку Дт 471 / Кт 661 на суму відпускних.

        Якщо компанія не має налаштованого резерву — мовчки пропустити.
        Якщо проводку вже створено для цього payslip — пропустити.
        """
        self.ensure_one()
        if self.vacation_reserve_reversal_move_id:
            return
        amount = self._get_vacation_accrual_amount()
        if not amount:
            return
        company = self.company_id
        reserve_acc = company.vacation_reserve_account_id
        payable_acc = company.vacation_payable_account_id
        journal = company.vacation_reserve_journal_id
        if not reserve_acc or not payable_acc or not journal:
            # Reserve not configured — skip silently
            return
        currency = company.currency_id
        amount = currency.round(amount) if currency else round(amount, 2)
        if not amount:
            return
        ref = _('Виплата відпускних %s (%s)') % (self.number or '', self.employee_id.name)
        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': fields.Date.context_today(self),
            'ref': ref,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {
                    'account_id': reserve_acc.id,
                    'name': ref,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': payable_acc.id,
                    'name': ref,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        })
        move.action_post()
        self.vacation_reserve_reversal_move_id = move
