from odoo import fields, models


class HrVersion(models.Model):
    _inherit = 'hr.version'

    salary_analytic_distribution = fields.Json(
        string='Аналітичний розподіл ЗП',
        help='Розподіл зарплатних витрат цього працівника за аналітичними '
             'рахунками (проєкти, центри витрат). Має пріоритет над розподілом '
             'підрозділу. Застосовується до рядків витрат (Дт 91/92/93/94, ЄСВ) '
             'у зарплатних проводках.',
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
