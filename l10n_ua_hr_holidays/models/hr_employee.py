from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    vacation_anchor_date = fields.Date(
        string='Vacation Work-Year Anchor',
        tracking=True,
        help='Date the annual (work-year) vacation seniority is counted from, '
             'when it differs from the hire date. Set by the inter-company '
             'transfer wizard in "Keep Work Year" mode: art. 9 §3 of the '
             'Vacation Law lets the previous employer\'s seniority continue '
             'when the compensation for unused days is transferred along with '
             'the employee. Empty — the work year runs from the hire date.')

    l10n_ua_vacation_opening_date = fields.Date(
        string='Vacation Opening Balance Date',
        tracking=True,
        groups='hr.group_hr_user',
        help='Дата вхідного залишку щорічної відпустки. Залишки рахуються '
             'від облікового періоду, що містить цю дату; періоди до неї в '
             'перенесення днів не входять.')
    l10n_ua_vacation_opening_days = fields.Float(
        string='Vacation Opening Balance (days)',
        tracking=True,
        groups='hr.group_hr_user',
        help='Невикористані дні основної щорічної відпустки за попередні '
             'робочі роки станом на початок облікового періоду, що містить '
             'дату вхідного залишку. Відпустки самого цього періоду '
             'враховуються як звичайно.')

    def _get_vacation_anchor_date(self):
        """Carried-over anchor wins over the hire date of the new contract."""
        self.ensure_one()
        return self.vacation_anchor_date or super()._get_vacation_anchor_date()

    def write(self, vals):
        res = super().write(vals)
        if {'l10n_ua_vacation_opening_date',
                'l10n_ua_vacation_opening_days'} & set(vals):
            balances = self.env['hr.vacation.balance'].sudo().search([
                ('employee_id', 'in', self.ids)])
            if balances:
                if vals.get('l10n_ua_vacation_opening_date'):
                    # The opening period itself must exist to carry the days.
                    for employee in self:
                        for leave_type in balances.filtered(
                                lambda b: b.employee_id == employee
                        ).leave_type_id:
                            balances._generate_period_chain(
                                employee, leave_type)
                balances._recompute_carryover_chain()
        return res

