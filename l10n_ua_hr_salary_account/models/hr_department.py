from odoo import api, fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    salary_expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат на ЗП',
        check_company=True,
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

    # hr.department не має _check_company_auto, тому check_company=True лише
    # звужує список вибору у формі. Перевірку під час збереження робимо явно
    # (issue #350): інакше проводка листка компанії A отримає рахунок компанії B.
    @api.constrains('company_id', 'salary_expense_account_id')
    def _check_salary_expense_account_company(self):
        self._check_company(['salary_expense_account_id'])
