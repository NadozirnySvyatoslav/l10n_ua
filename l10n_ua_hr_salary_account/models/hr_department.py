from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    salary_expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат на ЗП',
        help='Рахунок витрат для цього підрозділу (91/92/93/94). '
             'Якщо не вказано — використовується рахунок за замовчуванням '
             'з налаштувань зарплати.',
    )
    salary_analytic_distribution = fields.Json(
        string='Аналітичний розподіл ЗП',
        help='Типовий аналітичний розподіл зарплатних витрат підрозділу. '
             'Використовується, якщо у версії (контракті) працівника не задано '
             'власний розподіл.',
    )

    # Віджет analytic_distribution тягне analytic_precision з тієї самої моделі
    # (fieldDependencies у JS). Модель не успадковує analytic.mixin — вона має
    # власне окреме поле розподілу — тому точність оголошується явно, як це
    # робить сам analytic.mixin.
    analytic_precision = fields.Integer(
        store=False,
        default=lambda self: self.env['decimal.precision'].precision_get(
            'Percentage Analytic'),
    )
