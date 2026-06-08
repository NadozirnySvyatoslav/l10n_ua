from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    vacation_reserve_journal_id = fields.Many2one(
        'account.journal',
        string='Журнал резерву відпусток',
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        check_company=True,
    )
    vacation_reserve_account_id = fields.Many2one(
        'account.account',
        string='Рахунок резерву (471)',
        domain="[('company_ids', 'in', id)]",
        check_company=True,
        help='Забезпечення виплат відпусток — за замовч. 471',
    )
    vacation_payable_account_id = fields.Many2one(
        'account.account',
        string='Рахунок виплат (661)',
        domain="[('company_ids', 'in', id)]",
        check_company=True,
        help='Розрахунки з персоналом за зарплатою — за замовч. 661',
    )
    vacation_reserve_default_expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат за замовч.',
        domain="[('company_ids', 'in', id)]",
        check_company=True,
        help='Використовується якщо не задано на hr.job чи hr.employee '
             '(за замовч. 91 «Адміністративні витрати»)',
    )
    vacation_reserve_frequency = fields.Selection(
        selection=[
            ('monthly', 'Щомісяця'),
            ('quarterly', 'Щокварталу'),
        ],
        string='Періодичність нарахування',
        default='monthly',
    )
    vacation_reserve_annual_days = fields.Float(
        string='Дні відпустки на рік (за замовч.)',
        default=24.0,
        help='Базова річна норма відпустки для розрахунку резерву '
             '(за замовч. 24 к.д. — ст. 6 ЗУ № 504)',
    )
