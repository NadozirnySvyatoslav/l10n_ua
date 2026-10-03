import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrVersionAllowance(models.Model):
    _name = 'hr.version.allowance'
    _description = 'Version Allowance'
    _order = 'sequence, id'

    version_id = fields.Many2one(
        'hr.version',
        string='Employee Version',
        required=True,
        ondelete='cascade'
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='version_id.employee_id',
        store=True
    )
    allowance_type_id = fields.Many2one(
        'hr.allowance.type',
        string='Allowance Type',
        required=True
    )
    sequence = fields.Integer(
        string='Sequence',
        related='allowance_type_id.sequence',
        store=True
    )

    calculation_method = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percent_salary', 'Percent of Salary'),
        ('percent_min_wage', 'Percent of Minimum Wage'),
    ], string='Calculation Method', required=True, default='fixed')

    amount = fields.Float(
        string='Amount',
        help='Fixed amount if calculation method is fixed'
    )
    percent = fields.Float(
        string='Percent',
        help='Percentage if calculation method is percent'
    )

    calculated_amount = fields.Monetary(
        string='Calculated Amount',
        compute='_compute_calculated_amount',
        store=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='version_id.currency_id'
    )

    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    is_active = fields.Boolean(
        string='Active',
        compute='_compute_is_active',
        store=True
    )

    notes = fields.Text(string='Notes')

    def _get_minimum_wage(self, date=None):
        """Minimum wage of the version's company in force on `date`.

        Asked of the payroll parameters the same way a payslip asks: by the
        company the allowance belongs to and by the date it is computed for.
        Without the company the answer depended on the company switcher, and
        without the date a payslip recomputed for a past period took today's
        minimum wage.

        The configuration parameter behind it is reached only where
        `l10n_ua_hr_salary` is not installed and there are no payroll
        parameters at all: a payslip stops before this point when its
        company has none.
        """
        self.ensure_one()
        if 'hr.psp.parameters' in self.env:
            company = self.version_id.company_id or self.env.company
            date = date or self.date_from or fields.Date.context_today(self)
            params = self.env['hr.psp.parameters'].get_parameters(
                date, company.id)
            if params:
                return params.min_wage
        param = self.env['ir.config_parameter'].sudo().get_param(
            'l10n_ua_hr.minimum_wage', '8000'
        )
        return float(param)

    def _l10n_ua_amount_at(self, date=None, rate=None):
        """Сума надбавки у валюті компанії на задану дату або за курсом.

        Поле `calculated_amount` гривневе — не за домовленістю, а за
        побудовою: фіксована сума вводиться в гривні (валюта поля — валюта
        компанії), а відсоток від мінімалки рахується від гривневого
        законодавчого порога. Випадав лише відсоток від окладу: він
        успадковував валюту договору й давав 100 грн замість 4400 при
        окладі 1000 USD.

        Дата потрібна тільки цьому третьому методу, і саме тому розрахунок
        винесено в метод: збережене поле рахує його на дату початку
        надбавки (для картки договору й друкованої форми), а розрахунковий
        листок питає ту саму суму на дату свого періоду — інакше в одному
        листку оклад ішов би за курсом місяця, а надбавка до нього за
        курсом позаминулого року.

        `rate` важить більше за `date`, і саме тому існує: у листку курс
        живе в полі `salary_rate`, яке бухгалтер може виправити руками або
        вписати туди курс, якого в довіднику немає взагалі. Шукати курс
        самостійно означало б, що оклад і надбавка в одному документі
        рахуються за різними курсами, а в другому випадку — що надбавка
        падає з помилкою там, де оклад порахувався.
        """
        self.ensure_one()
        if self.calculation_method == 'fixed':
            return self.amount or 0.0
        if self.calculation_method == 'percent_min_wage':
            return self._get_minimum_wage(date) * (self.percent or 0) / 100
        if self.calculation_method == 'percent_salary':
            version = self.version_id
            if rate is not None:
                wage = (version.wage or 0.0) * rate
            else:
                wage = version._l10n_ua_wage_in_company_currency(
                    date or self.date_from or version.date_version)
            return wage * (self.percent or 0) / 100
        return 0.0

    # `version_id.salary_currency_id` у залежностях бути не може: поле
    # оголошує l10n_ua_hr_salary, а цей модуль про нього не знає — реєстр
    # впаде ще на завантаженні. Зміна валюти окладу тягне за собою зміну
    # самого окладу в переважній більшості випадків, а надбавку в листку
    # однаково перераховують на дату періоду.
    @api.depends('calculation_method', 'amount', 'percent', 'version_id.wage',
                 'date_from')
    def _compute_calculated_amount(self):
        for allowance in self:
            try:
                allowance.calculated_amount = allowance._l10n_ua_amount_at()
            except UserError:
                # Курсу на дату надбавки немає взагалі. Обнуляти не можна:
                # це поле бачить бухгалтер у картці договору, і нуль там
                # виглядав би як «надбавки немає». Лишаємо відсоток від
                # окладу як є — для гривневого окладу (тобто майже завжди)
                # це і є правильна сума, а для валютного платити за цим
                # числом ніхто не дасть: листок на відсутній курс
                # скаржиться голосно й розрахунок зупиняє.
                allowance.calculated_amount = (
                    (allowance.version_id.wage or 0) * (allowance.percent or 0) / 100)
                _logger.warning(
                    'Надбавка %s (%s): курсу валюти окладу на %s немає — '
                    'у картці договору сума без перерахунку',
                    allowance.allowance_type_id.name or allowance.id,
                    allowance.version_id.employee_id.name or '',
                    allowance.date_from or allowance.version_id.date_version)

    @api.depends('date_from', 'date_to')
    def _compute_is_active(self):
        today = fields.Date.today()
        for allowance in self:
            date_from_ok = not allowance.date_from or allowance.date_from <= today
            date_to_ok = not allowance.date_to or allowance.date_to >= today
            allowance.is_active = date_from_ok and date_to_ok
