from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    vacation_reserve_expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат на резерв',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
        help='Override для конкретного працівника. Якщо не задано — '
             'береться з hr.job, потім з компанії.',
    )

    def _get_vacation_reserve_expense_account(self):
        """Розрахувати рахунок витрат за пріоритетом:
        employee → job → company default.
        """
        self.ensure_one()
        if self.vacation_reserve_expense_account_id:
            return self.vacation_reserve_expense_account_id
        if self.job_id and self.job_id.vacation_reserve_expense_account_id:
            return self.job_id.vacation_reserve_expense_account_id
        return self.company_id.vacation_reserve_default_expense_account_id
