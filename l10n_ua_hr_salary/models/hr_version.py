from odoo import api, fields, models

# Contracts whose pay is not a salary: the tax social benefit is a reduction
# of the monthly salary only (ПКУ п. 169.1.1 — «у вигляді заробітної плати»),
# so a civil-law contract, a Diia.City gig contract (a civil-law contract by
# Закон № 1667-IX) or an author's contract never carries it, whatever the
# employee has applied for.
PSP_NON_SALARY_CONTRACT_TYPES = ('civil', 'gig', 'author')


class HrVersion(models.Model):
    _inherit = 'hr.version'

    # --- Заява про застосування ПСП (#322) ---
    # ПКУ п. 169.2.1: the benefit applies at one place of income only; п. 169.2.2:
    # the employee chooses that place by an application to the employer. The
    # application is filed for one employment, so it lives on the version and
    # not on the person: the same person on a secondary job at this company is
    # another employee record with its own version.
    #
    # Nothing recorded the application before, and every employee got the
    # benefit. The flag starts from the usual choice - the primary job applies,
    # an internal or external secondary job does not - and stays editable for
    # the person whose application was filed at the secondary job instead
    # (main job elsewhere without the benefit). `copy=True` keeps such a
    # manual choice on the next version of the contract.
    psp_application = fields.Boolean(
        string='PSP Application',
        compute='_compute_psp_application', store=True, readonly=False,
        copy=True, groups="hr.group_hr_user",
        help='The employee has filed the application for the tax social '
             'benefit (ПКУ п. 169.2.2) for this employment. The benefit applies '
             'at one place of income only: by default the primary job has it '
             'and a secondary job does not. Civil-law, gig and author contracts '
             'never get the benefit.')

    indexation_enabled = fields.Boolean(
        string='Індексувати ЗП',
        default=True,
        help='Проводити індексацію заробітної плати згідно із Законом '
             'про індексацію грошових доходів населення.'
    )
    indexation_base_month = fields.Date(
        string='Базовий місяць індексації',
        help='Місяць останнього підвищення посадового окладу / тарифної '
             'ставки. Накопичення індексу споживчих цін починається з '
             'наступного місяця. Оновлюється при кожному підвищенні зарплати.'
    )

    # --- Валюта нарахування (#206) ---
    salary_currency_id = fields.Many2one(
        'res.currency', string='Валюта окладу',
        default=lambda self: self.env.company.currency_id,
        help='Валюта, у якій встановлено оклад/ставку (для гіг-контрактів '
             'Дія.City, нерезидентів, валютних окладів). Для нарахування, '
             'податків і проведень сума перераховується у гривню за курсом '
             'на дату розрахункового листка.')

    # --- Форма оплати праці (#143) ---
    salary_form = fields.Selection(
        [('salary', 'Salaried'),
         ('hourly', 'Hourly'),
         ('piece', 'Piece Rate')],
        string='Salary Form', default='salary', required=True,
        help='Monthly salary: the salary over the norm of the month, for the '
             'hours worked. Hourly rate: the hourly rate of the tariff grade '
             'for the hours worked. Piece rate: the piece-work entries of the '
             'month instead of a salary.')

    # --- Надбавка за вислугу років (#143) ---
    seniority_enabled = fields.Boolean(
        string='Надбавка за вислугу років',
        help='Автоматично нараховувати надбавку за вислугу років на основі '
             'стажу роботи в компанії за налаштованою шкалою.')
    seniority_scale_id = fields.Many2one(
        'hr.seniority.scale', string='Шкала вислуги',
        help='Шкала «стаж → відсоток». Якщо не задано — береться перша активна '
             'шкала компанії.')

    @api.depends('employment_type_ua', 'contract_type_ua')
    def _compute_psp_application(self):
        for version in self:
            version.psp_application = (
                version.employment_type_ua == 'primary'
                and version.contract_type_ua not in PSP_NON_SALARY_CONTRACT_TYPES
            )
