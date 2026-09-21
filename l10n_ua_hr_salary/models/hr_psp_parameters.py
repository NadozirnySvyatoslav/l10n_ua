from odoo import models, fields, api
from odoo.tools import float_round


class HrPspParameters(models.Model):
    _name = 'hr.psp.parameters'
    _description = 'PSP Parameters'
    _order = 'year desc, date_from desc'
    _rec_name = 'display_name'

    year = fields.Integer(string='Year', required=True)
    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To')
    
    subsistence_minimum = fields.Float(
        string='Subsistence Minimum',
        required=True,
        help='Прожитковий мінімум для працездатних осіб'
    )
    min_wage = fields.Float(
        string='Minimum Wage',
        required=True,
        help='Мінімальна заробітна плата'
    )
    min_hourly_wage = fields.Float(
        string='Minimum Hourly Wage',
        required=True,
        default=0.0,
        help='Мінімальна погодинна заробітна плата'
    )
    psp_standard = fields.Float(
        string='PSP Standard (50%)',
        compute='_compute_psp_amounts',
        store=True,
        help='Податкова соціальна пільга 50% ПМ'
    )
    psp_150 = fields.Float(
        string='PSP 150%',
        compute='_compute_psp_amounts',
        store=True,
        help='Податкова соціальна пільга 150% (75% ПМ)'
    )
    psp_200 = fields.Float(
        string='PSP 200%',
        compute='_compute_psp_amounts',
        store=True,
        help='Податкова соціальна пільга 200% (100% ПМ)'
    )
    income_limit = fields.Float(
        string='Income Limit for PSP',
        compute='_compute_income_limit',
        store=True,
        help='Граничний дохід для застосування ПСП'
    )
    
    max_esv_base = fields.Float(
        string='Max ESV Base',
        compute='_compute_max_esv_base',
        store=True,
        help='Максимальна база нарахування ЄСВ (15 мін. зарплат)'
    )
    
    pdfo_rate = fields.Float(
        string='PDFO Rate (%)',
        default=18.0,
        help='Ставка податку на доходи фізичних осіб'
    )
    military_tax_rate = fields.Float(
        string='Military Tax Rate (%)',
        default=5.0,
        help='Ставка військового збору'
    )
    esv_rate = fields.Float(
        string='ESV Rate (%)',
        default=22.0,
        help='Ставка єдиного соціального внеску'
    )

    # --- Множники доплат за відхилення в табелі (#143) ---
    night_surcharge_rate = fields.Float(
        string='Night Surcharge (%)',
        default=20.0,
        help='Доплата за роботу в нічний час, % годинної ставки '
             '(ст. 108 КЗпП — не нижче 20%).'
    )
    overtime_multiplier = fields.Float(
        string='Overtime Multiplier',
        default=2.0,
        help='Множник оплати понаднормових годин (ст. 106 КЗпП — подвійний розмір).'
    )
    holiday_multiplier = fields.Float(
        string='Holiday Multiplier',
        default=2.0,
        help='Множник оплати роботи у святкові/неробочі дні '
             '(ст. 107 КЗпП — подвійний розмір).'
    )

    # --- Натуральний дохід / gross-up (#153) ---
    natural_coef_for_military = fields.Boolean(
        string='Натур. коеф. для ВЗ',
        default=True,
        help='Застосовувати натуральний коефіцієнт (п. 164.5 ПКУ) також до '
             'бази військового збору з натурального доходу. Вимкніть, якщо ВЗ '
             'утримується від звичайної вартості без гросс-апу.'
    )

    # --- Індексація ЗП (#138) ---
    indexation_threshold = fields.Float(
        string='Поріг індексації (%)',
        default=101.0,
        help='Поріг наростаючого індексу споживчих цін, при перевищенні '
             'якого проводиться індексація (Порядок №1078 — 101%).'
    )

    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    
    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    @api.depends('subsistence_minimum')
    def _compute_psp_amounts(self):
        for rec in self:
            rec.psp_standard = rec.subsistence_minimum * 0.5
            rec.psp_150 = rec.subsistence_minimum * 0.75
            rec.psp_200 = rec.subsistence_minimum

    @api.depends('subsistence_minimum')
    def _compute_income_limit(self):
        # п. 169.4.1 ПКУ: ПМ для працездатних на 1 січня × 1,4, округлений до
        # найближчих 10 грн (2025 — 4240, 2026 — 4660). Раніше тут стояло
        # «× 1,4 × 10», і ПСП надавалась при доході до ~42 тис. грн (#329).
        for rec in self:
            rec.income_limit = float_round(
                rec.subsistence_minimum * 1.4, precision_rounding=10)

    @api.depends('min_wage')
    def _compute_max_esv_base(self):
        for rec in self:
            rec.max_esv_base = rec.min_wage * 15

    @api.depends('year', 'date_from')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.year} ({rec.date_from})'

    @api.model
    def get_parameters(self, date=None, company_id=None):
        """Get PSP parameters for given date and company.

        Every company keeps its own set of records (each may have its own
        administrator), so only records of that company are considered.
        Payslip code must pass the payslip's company explicitly: the default
        (the company active in the session switcher) is only meant for calls
        made outside a payslip. The lookup runs as superuser so the result
        does not depend on which companies are enabled in the switcher of
        whoever triggers the computation.
        """
        if date is None:
            date = fields.Date.today()
        if company_id is None:
            company_id = self.env.company.id

        return self.sudo().search([
            ('date_from', '<=', date),
            '|', ('date_to', '>=', date), ('date_to', '=', False),
            ('company_id', '=', company_id),
            ('active', '=', True),
        ], order='date_from desc', limit=1)

    @api.model
    def _seed_company_parameters(self, companies=None):
        """Create each company's records from the statutory reference.

        All companies are treated alike: records are built from
        `hr.psp.parameters.template` (loaded from the module data), never
        copied from another company. A company without any parameters gets
        every period; otherwise only periods newer than its latest record are
        added. Existing records are never touched, and a period the company's
        administrator deleted is not brought back.
        """
        Params = self.sudo().with_context(active_test=False)
        if companies is None:
            companies = self.env['res.company'].sudo().with_context(
                active_test=False).search([])
        templates = self.env['hr.psp.parameters.template'].sudo().search([])
        latest = dict(Params._read_group(
            [('company_id', 'in', companies.ids)],
            ['company_id'], ['date_from:max']))
        vals_list = [
            template._company_values(company)
            for company in companies
            for template in templates
            if not latest.get(company) or template.date_from > latest[company]
        ]
        return Params.create(vals_list)

    _unique_year_date_from_company_id = models.Constraint(
        'unique(year, date_from, company_id)',
        'Parameters for this period already exist!',
    )
