from datetime import datetime, time

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

    # Leave kinds compensated on dismissal (art. 24 of the Vacation Law):
    # the annual leaves, basic and additional, and the additional leave of
    # workers with children.
    _L10N_UA_COMPENSATED_CATEGORIES = (
        'annual_basic', 'annual_additional', 'annual_hazardous',
        'annual_special', 'annual_irregular', 'social_children',
    )

    def _l10n_ua_unused_vacation_on(self, day):
        """Unused vacation days on the last day of work.

        Returns a list of ``(balance, days)`` — one accounting period per
        leave type, the one containing `day`, with a positive balance. The
        chain of periods is brought up to that day first for the leave types
        whose balances are calculated automatically.
        """
        self.ensure_one()
        Balance = self.env['hr.vacation.balance'].sudo()
        leave_types = self.env['hr.work.entry.type'].sudo().search([
            ('ua_leave_category', 'in', self._L10N_UA_COMPENSATED_CATEGORIES),
            ('annual_days', '>', 0),
        ])
        result = []
        for leave_type in leave_types:
            if leave_type.ua_auto_calc_balance:
                period = Balance._ensure_periods_up_to(self, leave_type, day)
            else:
                period = Balance.search([
                    ('employee_id', '=', self.id),
                    ('leave_type_id', '=', leave_type.id),
                    ('period_start', '<=', day),
                    ('period_end', '>=', day),
                ], limit=1)
            if not period:
                continue
            days = period._l10n_ua_unused_days_on(day)
            if days > 0:
                result.append((period, days))
        return result

    def _l10n_ua_average_daily_salary_on(self, day):
        """Average daily salary for vacation pay and compensation on `day`
        (Порядок №100: the 12 months before the month of `day`)."""
        self.ensure_one()
        start = datetime.combine(day, time.min)
        leave = self.env['hr.leave'].new({
            'employee_id': self.id,
            'request_date_from': day,
            'request_date_to': day,
            'date_from': start,
            'date_to': start,
        })
        return leave._calculate_average_salary()
