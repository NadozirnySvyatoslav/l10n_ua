from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
import calendar
import logging

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _description = 'Payslip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, employee_id'

    name = fields.Char(
        string='Reference',
        required=True,
        default='New',
        tracking=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True
    )
    version_id = fields.Many2one(
        'hr.version',
        string='Employee Version',
        compute='_compute_version_id',
        store=True,
        readonly=False
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id'
    )

    # --- Валютне нарахування (#206) ---
    salary_currency_id = fields.Many2one(
        'res.currency',
        string='Валюта окладу',
        compute='_compute_salary_currency',
        store=True,
        help='Валюта нарахування окладу (з версії/договору). Якщо відрізняється '
             'від валюти компанії — оклад перераховується у гривню за курсом.',
    )
    salary_rate = fields.Float(
        string='Курс окладу',
        digits=(16, 6),
        compute='_compute_salary_rate',
        store=True,
        readonly=False,
        help='Курс валюти окладу до гривні на дату розрахунку (грн за одиницю). '
             'Підставляється з довідника курсів; можна відкоригувати вручну.',
    )


    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Payslip Batch'
    )
    
    date_from = fields.Date(
        string='Date From',
        required=True,
        tracking=True
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        tracking=True
    )
    
    # Employee data (snapshot)
    rnokpp = fields.Char(
        string='RNOKPP',
        related='employee_id.rnokpp'
    )
    
    # Working time
    scheduled_days = fields.Integer(
        string='Scheduled Days',
        help='Working days in period according to calendar'
    )
    scheduled_hours = fields.Float(
        string='Scheduled Hours'
    )
    worked_days = fields.Integer(
        string='Worked Days',
        default=0
    )
    worked_hours = fields.Float(
        string='Worked Hours',
        default=0.0
    )
    # Відхилення в табелі для авто-доплат (#143).
    night_hours = fields.Float(string='Night Hours', default=0.0)
    overtime_hours = fields.Float(string='Overtime Hours', default=0.0)
    holiday_hours = fields.Float(string='Holiday Hours', default=0.0)

    # Accruals
    accrual_ids = fields.One2many(
        'hr.payslip.accrual',
        'payslip_id',
        string='Accruals'
    )
    gross_salary = fields.Monetary(
        string='Gross Salary',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    # PSP (Tax Social Benefit)
    psp_eligible = fields.Boolean(
        string='PSP Eligible',
        compute='_compute_psp',
        store=True
    )
    psp_type = fields.Selection([
        ('none', 'None'),
        ('standard', 'Standard (50%)'),
        ('150', '150%'),
        ('200', '200%'),
    ], string='PSP Type',
       compute='_compute_psp_type', store=True, readonly=False)

    # Flags for special tax regimes
    is_disability = fields.Boolean(
        string='Disability',
        compute='_compute_employee_benefits',
        store=True,
        help='Employee has disability benefit (reduced ESV rate 8.41%)'
    )
    is_diia_city = fields.Boolean(
        string='Diia.City Employee',
        compute='_compute_employee_benefits',
        store=True,
        help='Diia.City gig employee (5% PDFO, no ESV)'
    )
    psp_amount = fields.Monetary(
        string='PSP Amount',
        compute='_compute_psp',
        store=True,
        currency_field='currency_id'
    )
    
    # Taxes
    pdfo_base = fields.Monetary(
        string='PDFO Base',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    pdfo_rate = fields.Float(
        string='PDFO Rate (%)',
        default=18.0
    )
    pdfo_amount = fields.Monetary(
        string='PDFO Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    military_tax_base = fields.Monetary(
        string='Military Tax Base',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    military_tax_rate = fields.Float(
        string='Military Tax Rate (%)',
        default=5.0
    )
    military_tax_amount = fields.Monetary(
        string='Military Tax Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    # ESV (employer)
    esv_base = fields.Monetary(
        string='ESV Base',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    esv_rate = fields.Float(
        string='ESV Rate (%)',
        default=22.0
    )
    esv_amount = fields.Monetary(
        string='ESV Amount',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    # Deductions
    deduction_ids = fields.One2many(
        'hr.payslip.deduction',
        'payslip_id',
        string='Deductions'
    )
    total_deductions = fields.Monetary(
        string='Total Deductions',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    other_deductions = fields.Monetary(
        string='Other Deductions',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    # Net
    net_salary = fields.Monetary(
        string='Net Salary',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )

    advance_amount = fields.Monetary(
        string='Advance',
        compute='_compute_advance_amount',
        store=True,
        currency_field='currency_id'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verify', 'Waiting'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    
    notes = fields.Text(string='Notes')

    # Ретро-перерахунки (#151): різниці, перенесені В цей (поточний) листок,
    # та перерахунки, ДЖЕРЕЛОМ яких був цей (закритий) листок.
    retro_incoming_ids = fields.One2many(
        'hr.payslip.retro', 'target_payslip_id', string='Retro Adjustments',
        copy=False)
    retro_source_ids = fields.One2many(
        'hr.payslip.retro', 'source_payslip_id', string='Retro (as source)',
        copy=False)

    @api.depends('employee_id')
    def _compute_employee_benefits(self):
        """Compute employee benefit flags for special tax regimes"""
        for payslip in self:
            is_disability = False
            is_diia_city = False

            if payslip.employee_id:
                # Check for disability benefits
                if payslip.employee_id.benefit_ids:
                    for benefit in payslip.employee_id.benefit_ids:
                        code_lower = (benefit.code or '').lower()
                        name_lower = (benefit.name or '').lower()
                        if 'disability' in code_lower or 'інвалід' in name_lower:
                            is_disability = True
                            break

                # Check for Diia.City status from contract version
                version = payslip.version_id or payslip.employee_id.current_version_id
                if version:
                    is_diia_city = bool(version.diia_city_employee) or \
                        version.contract_type_ua == 'gig'

            payslip.is_disability = is_disability
            payslip.is_diia_city = is_diia_city

    @api.depends('employee_id',
                 'employee_id.disability_group',
                 'employee_id.chornobyl_category',
                 'employee_id.veteran_status',
                 'employee_id.is_single_parent',
                 'employee_id.dependents_count',
                 'employee_id.benefit_ids')
    def _compute_psp_type(self):
        """Determine PSP type per ПК ст. 169.

        Priority (highest wins): 200% > 150% > standard > none

        200% applies to (ст. 169.1.4):
        - Disability group I
        - Chornobyl categories 1, 2
        - Combat / war veterans

        150% applies to (ст. 169.1.3):
        - Disability groups II, III
        - Chornobyl categories 3, 4
        - Single parents with at least 1 dependent
        - Any explicit benefit marked psp_type='150'

        Standard applies to (ст. 169.1.1) any employee meeting income threshold.

        Final PSP type is the maximum of all applicable rules + any benefit's
        own psp_type setting.
        """
        psp_priority = {'none': 0, 'standard': 1, '150': 2, '200': 3}
        for payslip in self:
            employee = payslip.employee_id
            if not employee:
                payslip.psp_type = 'none'
                continue

            psp_type = 'standard'  # baseline — final eligibility checked in _compute_psp

            # --- 200% rules (highest priority) ---
            if employee.disability_group == '1':
                psp_type = '200'
            elif employee.chornobyl_category in ('1', '2'):
                psp_type = '200'
            elif employee.veteran_status in ('combat', 'war'):
                psp_type = '200'

            # --- 150% rules (only if not already 200%) ---
            if psp_type != '200':
                if employee.disability_group in ('2', '3'):
                    psp_type = '150'
                elif employee.chornobyl_category in ('3', '4'):
                    psp_type = '150'
                elif employee.is_single_parent and employee.dependents_count >= 1:
                    psp_type = '150'

            # --- Benefit-level overrides (catalog `psp_type`) ---
            for benefit in employee.benefit_ids:
                if benefit.psp_type and psp_priority.get(benefit.psp_type, 0) > psp_priority.get(psp_type, 0):
                    psp_type = benefit.psp_type

            payslip.psp_type = psp_type

    @api.depends('employee_id', 'date_from')
    def _compute_version_id(self):
        for payslip in self:
            if payslip.employee_id:
                # Get version at payslip date
                date = payslip.date_from or fields.Date.today()
                versions = payslip.employee_id.version_ids.filtered(
                    lambda v: v.date_version <= date and v.contract_date_start
                ).sorted('date_version', reverse=True)
                payslip.version_id = versions[0] if versions else payslip.employee_id.current_version_id
            else:
                payslip.version_id = False

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Clear employee if from a different company (preserve shared employees)."""
        if self.employee_id and self.employee_id.company_id \
                and self.employee_id.company_id != self.company_id:
            self.employee_id = False

    @api.depends('gross_salary', 'psp_type', 'employee_id.dependents_count',
                 'employee_id.is_single_parent')
    def _compute_psp(self):
        """Compute PSP eligibility and amount per ПК ст. 169.

        Eligibility: gross_salary ≤ income_limit (or income_limit × dependents_count
        for multi-dependent families — ПК 169.4.1, п. «в»).

        Amount: base PSP (by psp_type) + extra PSP for each dependent beyond the first
        (only if employee has 2+ children — ПК 169.1.2, п. «б»).
        Single parent gets double base PSP × dependents_count (covers «двойна ПСП»).
        """
        for payslip in self:
            params = self.env['hr.psp.parameters'].get_parameters(payslip.date_to)
            if not params:
                payslip.psp_eligible = False
                payslip.psp_amount = 0.0
                continue

            employee = payslip.employee_id
            dependents = employee.dependents_count if employee else 0

            # Income limit for families with 2+ dependents is multiplied by N children
            # (ПК 169.4.1 п. «в») — allows higher-earning parents to still qualify
            effective_limit = params.income_limit
            if dependents >= 2:
                effective_limit = params.income_limit * dependents

            payslip.psp_eligible = payslip.gross_salary <= effective_limit

            if not (payslip.psp_eligible and payslip.psp_type != 'none'):
                payslip.psp_amount = 0.0
                continue

            # Base PSP per psp_type
            if payslip.psp_type == 'standard':
                base = params.psp_standard
            elif payslip.psp_type == '150':
                base = params.psp_150
            elif payslip.psp_type == '200':
                base = params.psp_200
            else:
                base = 0.0

            # Extra ПСП на дітей (ст. 169.1.2):
            # When employee has 2+ dependents — additional PSP applies per child
            # (base PSP × N children). Single parent gets 150% PSP per child.
            if employee and dependents >= 2:
                # multiply base by number of dependent children
                # Single parent multiplier is captured by psp_type='150' choice in _compute_psp_type
                payslip.psp_amount = base * dependents
            else:
                payslip.psp_amount = base

    @api.depends(
        'accrual_ids.amount',
        'deduction_ids.amount',
        'psp_amount',
        'pdfo_rate',
        'military_tax_rate',
        'esv_rate',
        'is_diia_city',
        'is_disability'
    )
    def _compute_amounts(self):
        for payslip in self:
            # Gross salary
            gross = sum(a.amount for a in payslip.accrual_ids)
            payslip.gross_salary = gross

            # Determine effective tax rates based on employee status
            pdfo_rate = payslip.pdfo_rate
            esv_rate = payslip.esv_rate
            military_rate = payslip.military_tax_rate

            # Diia.City: 5% PDFO, no ESV, no military tax
            if payslip.is_diia_city:
                pdfo_rate = 5.0
                esv_rate = 0.0
                military_rate = 0.0

            # Disability: 8.41% ESV rate
            if payslip.is_disability and not payslip.is_diia_city:
                esv_rate = 8.41

            # Натуральний коефіцієнт (п. 164.5 ПКУ) для гросс-апу негрошового
            # доходу: К = 100 / (100 − ставка ПДФО). Дохід у натуральній формі
            # приводиться до "брутто" перед оподаткуванням ПДФО/ВЗ (#153).
            params = self.env['hr.psp.parameters'].get_parameters(payslip.date_to)
            natural_coef = 100.0 / (100.0 - pdfo_rate) if pdfo_rate < 100 else 1.0
            mil_natural = (params.natural_coef_for_military
                           if params else True)
            mil_coef = natural_coef if mil_natural else 1.0

            # PDFO base and amount
            pdfo_taxable = sum(
                (a.amount * natural_coef if a.is_in_kind else a.amount)
                for a in payslip.accrual_ids
                if a.is_taxable_pdfo
            )
            payslip.pdfo_base = max(0, pdfo_taxable - payslip.psp_amount)
            payslip.pdfo_amount = round(payslip.pdfo_base * pdfo_rate / 100, 2)

            # Military tax
            military_taxable = sum(
                (a.amount * mil_coef if a.is_in_kind else a.amount)
                for a in payslip.accrual_ids
                if a.is_military_tax
            )
            payslip.military_tax_base = military_taxable
            payslip.military_tax_amount = round(military_taxable * military_rate / 100, 2)

            # ESV (employer contribution) — на звичайну вартість, без гросс-апу
            esv_taxable = sum(
                a.amount for a in payslip.accrual_ids
                if a.is_esv_base
            )

            if payslip.is_diia_city:
                # No ESV for Diia.City
                payslip.esv_base = 0.0
                payslip.esv_amount = 0.0
            else:
                min_esv_base = params.min_wage if params else 8000
                max_esv_base = params.max_esv_base if params else 120000

                payslip.esv_base = min(max(esv_taxable, min_esv_base), max_esv_base)
                payslip.esv_amount = round(payslip.esv_base * esv_rate / 100, 2)
            
            # Other deductions (excluding taxes)
            other_ded = sum(
                d.amount for d in payslip.deduction_ids 
                if d.deduction_type_id.category not in ('tax',)
            )
            payslip.other_deductions = other_ded
            
            # Total deductions
            payslip.total_deductions = (
                payslip.pdfo_amount + 
                payslip.military_tax_amount + 
                payslip.other_deductions
            )
            
            # Net salary
            payslip.net_salary = gross - payslip.total_deductions

    @api.depends('deduction_ids.amount', 'deduction_ids.deduction_type_id')
    def _compute_advance_amount(self):
        for payslip in self:
            advance_ded = payslip.deduction_ids.filtered(
                lambda d: d.deduction_type_id.code == 'ADVANCE'
            )
            payslip.advance_amount = sum(advance_ded.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.payslip') or 'New'
        return super().create(vals_list)

    def action_compute_sheet(self):
        """Compute payslip amounts"""
        for payslip in self:
            if payslip.state != 'draft':
                continue
            
            payslip._compute_working_days()
            payslip._generate_accruals()
            payslip._generate_deductions()
        
        return True

    def _daily_hour_norm(self):
        """Денна норма годин з урахуванням ставки зайнятості (work_rate).

        0.5 ставки → 4 год/день при 8-годинному дні. Базова денна норма —
        з графіка/тижневої норми версії, помножена на work_rate. Так табель
        неповного робочого часу відображає пропорційно зменшену норму, а не
        фіксовані 8 год (#149).
        """
        self.ensure_one()
        version = self.version_id
        if version and getattr(version, 'scheduled_hours_day', 0.0):
            return version.scheduled_hours_day
        base = 8.0
        if version:
            base *= (version.work_rate or 1.0)
        return base

    def _compute_working_days(self):
        """Calculate scheduled and worked days"""
        self.ensure_one()
        if not self.date_from or not self.date_to:
            return

        # Simple calculation - count weekdays
        month_start = self.date_to.replace(day=1)
        month_end = month_start + relativedelta(months=1, days=-1)

        total_scheduled = 0
        curr = month_start
        while curr <= month_end:
            if curr.weekday() < 5:  # Monday to Friday
                total_scheduled += 1
            curr += relativedelta(days=1)

        daily_norm = self._daily_hour_norm()
        self.scheduled_days = total_scheduled
        self.scheduled_hours = total_scheduled * daily_norm
        
        # get amount of working days from timesheet
        if 'hr.timesheet.line' in self.env:
            ts_line = self.env['hr.timesheet.line'].search([
                ('employee_id', '=', self.employee_id.id),
                ('timesheet_id.month', '=', str(self.date_to.month)),
                ('timesheet_id.year', '=', self.date_to.year),
                ('timesheet_id.state', 'in', ['confirmed', 'approved'])
            ], limit=1, order='timesheet_id desc')
            
            if ts_line:
                self.worked_days = ts_line.worked_days
                self.worked_hours = ts_line.worked_hours
                # Відхилення для авто-доплат (нічні/понаднормові/святкові).
                self.night_hours = ts_line.night_hours
                self.overtime_hours = ts_line.overtime_hours
                self.holiday_hours = getattr(ts_line, 'holiday_hours', 0.0)
                # in case if there is multiplier in timesheets
                if ts_line.scheduled_days:
                    self.scheduled_days = ts_line.scheduled_days
                    self.scheduled_hours = ts_line.scheduled_days * daily_norm
                return

        # default if there is no timesheets
        worked = 0
        curr = self.date_from
        while curr <= self.date_to:
            if curr.weekday() < 5:
                worked += 1
            curr += relativedelta(days=1)
        self.worked_days = worked
        self.worked_hours = worked * daily_norm


    @api.depends('version_id', 'version_id.salary_currency_id')
    def _compute_salary_currency(self):
        for slip in self:
            version_cur = slip.version_id.salary_currency_id \
                if slip.version_id else False
            slip.salary_currency_id = version_cur or slip.company_id.currency_id

    @api.depends('salary_currency_id', 'date_to', 'company_id')
    def _compute_salary_rate(self):
        for slip in self:
            cur = slip.salary_currency_id
            comp_cur = slip.company_id.currency_id
            if cur and comp_cur and cur != comp_cur and slip.date_to:
                # `round=False`: інакше курс округлюється до копійки, бо
                # `_convert` заокруглює результат за валютою призначення.
                # Поле оголошене на шість знаків не з примхи — офіційний курс
                # НБУ має чотири, і 44.2680, стиснутий до 44.27, дає зайві дві
                # гривні на кожній тисячі доларів окладу.
                slip.salary_rate = cur._convert(
                    1.0, comp_cur, slip.company_id, slip.date_to, round=False)
            else:
                slip.salary_rate = 1.0

    def _check_salary_rate_known(self):
        """Не рахувати валютний оклад, поки курс невідомий.

        `_convert` за відсутності запису курсу мовчки бере 1.0, тож оклад
        1000 USD виплатився б як 1000 грн — помилка в сорок разів, і не в
        бік працівника. Валютний оклад без курсу — не нуль і не «як є», а
        незаповнений довідник: краще зупинити розрахунок і сказати, чого
        бракує.

        Курс може прийти двома шляхами, і обидва тут законні: з довідника
        валют або руками в поле «Курс окладу» (воно `readonly=False` саме
        для цього). Тому відмовляємо лише коли жоден зі шляхів не спрацював:
        у довіднику запису немає **і** в полі лишилась одиниця, яку туди
        поклав обчислювач за відсутності курсу. Вписаний руками курс
        перевірку проходить — інакше повідомлення радило б те, чого сам код
        не приймає.

        Нуль у полі — окремий випадок: це не «курс один до одного», а
        стертий курс, і множення на нього дало б нульову зарплату.
        """
        self.ensure_one()
        cur = self.salary_currency_id
        comp_cur = self.company_id.currency_id
        if not cur or not comp_cur or cur == comp_cur:
            return

        if not self.salary_rate:
            raise UserError(_(
                'Курс окладу для %(employee)s дорівнює нулю. Оклад у '
                '%(currency)s не можна перерахувати в гривню — вкажіть курс '
                'у полі «Курс окладу» або внесіть його в довідник валют.',
                employee=self.employee_id.name or '',
                currency=cur.name))

        latest_rate = self.env['res.currency.rate'].search([
            ('currency_id', '=', cur.id),
            ('company_id', 'in', [self.company_id.id, False]),
            ('name', '<=', self.date_to),
        ], order='name desc', limit=1)

        if not latest_rate and self.salary_rate == 1.0:
            raise UserError(_(
                'Оклад працівника %(employee)s встановлено в %(currency)s, але '
                'курс цієї валюти на %(date)s не заданий. Без курсу оклад '
                'потрапив би в розрахунок як гривневий. Внесіть курс у '
                'довідник валют або вкажіть курс у полі «Курс окладу».',
                employee=self.employee_id.name or '',
                currency=cur.name,
                date=fields.Date.to_string(self.date_to)))

        # Застарілий курс не блокуємо: у довіднику законно тримати лише дати
        # зміни, і курс з 1 числа чинний до кінця місяця. Але курс, старший за
        # сам період, — це вже забутий довідник, і мовчати про це не варто:
        # розрахунок піде за ціною позаминулого разу.
        if latest_rate and self.date_from and latest_rate.name < self.date_from:
            _logger.warning(
                'Розрахунковий листок %s: курс %s узято з %s — раніше за '
                'початок періоду (%s). Перевірте, чи довідник курсів свіжий.',
                self.name or self.id, cur.name,
                fields.Date.to_string(latest_rate.name),
                fields.Date.to_string(self.date_from))

    def _convert_salary_to_company(self, amount):
        """Перерахувати суму окладу з валюти окладу у валюту компанії.

        Без запасного `or 1.0`: нульовий курс — це не «один до одного», а
        привід зупинитись, і саме це робить `_check_salary_rate_known` перед
        нарахуванням.
        """
        self.ensure_one()
        if not amount:
            return amount
        cur = self.salary_currency_id
        comp_cur = self.company_id.currency_id
        if cur and comp_cur and cur != comp_cur:
            return amount * self.salary_rate
        return amount

    def _get_effective_wage(self, version):
        """Get effective wage (in company currency) considering staffing table.

        Оклад може бути встановлений в іноземній валюті (#206) — тут він
        перераховується у валюту компанії за курсом розрахункового листка,
        тож усі похідні розрахунки (оклад, доплати, індексація) — у гривні.

        The staffing table is asked about the period rather than read off
        the version: `version.staffing_line_id` answers the card's question —
        which position applies now — while a payslip asks which one applied
        then. The difference shows on a recalculation: without this, a payslip
        for March recomputed in September would take the salary approved in
        June.

        The anchor is the start of the period, the same one the choice of
        version already stands on (`_compute_version_id`). Neither mechanism
        notices a change in the middle of a month; proration will come
        separately, and for versions and staffing lines at once.

        The two sources return separately, and on purpose. `salary_rate` is the
        rate of the currency the *version's* wage is denominated in, so putting
        the staffing salary through it converts a figure with the wrong rate
        entirely — and does so precisely when the version carries no wage,
        which is the only case the fallback is reached in. A version paid in
        USD would have turned a position of 20 000 UAH into 830 000. The line
        converts its own money.
        """
        wage = version.wage or 0.0
        if wage > 0:
            return self._convert_salary_to_company(wage)

        # Check company setting for staffing table fallback
        setting = self.company_id.wage_from_staffing or 'both'
        if setting in ('fallback', 'both'):
            # `with_company`, not `sudo`: the staffing table is read
            # through a rule on `company_id in company_ids`, that is, on
            # the companies ticked in the switcher. Without this the wage
            # would depend on what the officer happens to have selected,
            # and read zero for a company left out. `with_company` states
            # that the payslip's own company is the one being calculated,
            # and raises AccessError when there is no right to it — where
            # sudo would quietly calculate somebody else's.
            staffing = self.env['hr.staffing.table'].with_company(
                version.company_id)._resolve(
                    version.company_id, version.department_id,
                    version.job_id,
                    self.date_from or fields.Date.context_today(self))
            if staffing.salary:
                return staffing._salary_in_company_currency(
                    self.date_from or fields.Date.context_today(self))

        return 0.0

    def _generate_accruals(self):
        """Generate accrual lines based on employee version.

        Only auto-generated accruals are deleted and recreated.
        Manual accruals (bonuses, premiums added by user) are preserved.
        """
        self.ensure_one()
        # Delete only auto-generated accruals, preserve manual ones (bonuses, premiums)
        self.accrual_ids.filtered('is_auto_generated').unlink()

        if not self.version_id:
            return

        self._check_salary_rate_known()

        version = self.version_id

        salary_type = self.env['hr.accrual.type'].search([('code', '=', 'SALARY')], limit=1)
        params = self.env['hr.psp.parameters'].get_parameters(self.date_to)

        # Форма оплати праці: відрядна замінює окладну/тарифну (#143).
        is_piece = getattr(version, 'salary_form', 'time') == 'piece'

        # If the user already entered a base-wage accrual by hand, don't add the
        # version-based one on top — that would double-count the salary.
        has_manual_salary = salary_type and any(
            a.accrual_type_id == salary_type and not a.is_auto_generated
            for a in self.accrual_ids
        )

        if salary_type and not has_manual_salary and not is_piece:
            # tariff grade calculations
            if version.tariff_grade_id:

                if self.worked_hours > 0:                                   # Guard clause
                    min_hourly_wage = params.min_hourly_wage if params else 52.0
                    tariff = version.tariff_grade_id
                    coef = tariff.coefficient or 1.0

                    # Priority: hourly rate -> monthly rate -> 0
                    if tariff.hourly_rate:
                        hourly_rate = tariff.hourly_rate * coef
                    elif tariff.min_salary and self.scheduled_hours > 0:
                        hourly_rate = (tariff.min_salary * coef) / self.scheduled_hours
                    else:
                        hourly_rate = 0.0


                    # Floor — never below statutory minimum hourly wage
                    hourly_rate = max(hourly_rate, min_hourly_wage)

                    if hourly_rate > 0 and self.worked_hours > 0:
                        amount = round(hourly_rate * self.worked_hours, 2)
                        self.env['hr.payslip.accrual'].create({
                            'payslip_id': self.id,
                            'accrual_type_id': salary_type.id,
                            'quantity': self.worked_hours,
                            'rate': hourly_rate,
                            'amount': amount,
                            'is_auto_generated': True,
                            'notes': f'Тариф: {tariff.name} (коеф. {coef})',
                       })
            
            # monthly wage calculation
            else:
                effective_wage = self._get_effective_wage(version)
                # Ставка зайнятості (work_rate): 0.5 ставки → половина окладу.
                # Тарифний (погодинний) шлях цього не потребує — там
                # пропорційність дають фактично відпрацьовані години.
                monthly_wage = effective_wage * (version.work_rate or 1.0)
                if monthly_wage and self.scheduled_days > 0:
                    # scheduled_days - number of expected working days in the months
                    daily_rate = monthly_wage / self.scheduled_days
                    
                    if self.worked_days >= self.scheduled_days:
                        amount = monthly_wage  # full (rate-adjusted) amount if worked all days
                    else:
                        amount = daily_rate * self.worked_days

                    self.env['hr.payslip.accrual'].create({
                        'payslip_id': self.id,
                        'accrual_type_id': salary_type.id,
                        'quantity': self.worked_days,
                        'rate': daily_rate,
                        'amount': round(amount, 2),
                        'is_auto_generated': True,
                    })

        # Відрядна оплата — замість окладу (#143).
        if is_piece:
            self._generate_piece_work(version, params)

        # Version allowances
        allowance_type = self.env['hr.accrual.type'].search([('code', '=', 'ALLOWANCE')], limit=1)
        if allowance_type:
            for allowance in version.allowance_ids.filtered('is_active'):
                self.env['hr.payslip.accrual'].create({
                    'payslip_id': self.id,
                    'accrual_type_id': allowance_type.id,
                    'quantity': 1,
                    # Не збережене `calculated_amount`, а сума за курсом
                    # цього листка: воно пораховане на дату початку надбавки,
                    # і для відсотка від валютного окладу це курс, якому може
                    # бути рік. Курс передаємо свій, а не дату, бо `salary_rate`
                    # бухгалтер може виправити руками — інакше оклад пішов би
                    # за виправленим курсом, а надбавка до нього за
                    # довідниковим.
                    'amount': allowance._l10n_ua_amount_at(
                        self.date_to, rate=self.salary_rate),
                    'notes': allowance.allowance_type_id.name,
                    'is_auto_generated': True,
                })

        # Авто-доплати за відхилення в табелі (нічні/понаднормові/святкові) — #143.
        self._generate_time_surcharges(version, params)

        # Індексація заробітної плати — #138.
        self._generate_indexation(version, params)

        # Надбавка за вислугу років — #143.
        self._generate_seniority(version, params)

    def _generate_piece_work(self, version, params):
        """Створити авто-нарахування «Відрядна оплата» за нарядами періоду.

        Підсумовує наряди відрядної оплати (hr.piece.work.entry) працівника,
        дата яких потрапляє в період нарахування, у єдине нарахування PIECE.
        """
        self.ensure_one()
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'PIECE')], limit=1)
        if not acc_type:
            return
        entries = self.env['hr.piece.work.entry'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('company_id', '=', self.company_id.id),
        ])
        if not entries:
            return
        total_qty = sum(entries.mapped('quantity'))
        total_amount = round(sum(entries.mapped('amount')), 2)
        if total_amount <= 0:
            return
        self.env['hr.payslip.accrual'].create({
            'payslip_id': self.id,
            'accrual_type_id': acc_type.id,
            'quantity': total_qty,
            'amount': total_amount,
            'is_auto_generated': True,
            'notes': _('Відрядна оплата: %d наряд(ів)') % len(entries),
        })

    def _generate_seniority(self, version, params):
        """Створити авто-надбавку «За вислугу років» на основі стажу.

        Відсоток надбавки береться зі ступінчастої шкали (hr.seniority.scale)
        за стажем роботи в компанії. База — посадовий оклад (з урахуванням
        ставки зайнятості), пропорційно відпрацьованому часу.
        """
        self.ensure_one()
        if not getattr(version, 'seniority_enabled', False):
            return
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'SENIORITY')], limit=1)
        if not acc_type:
            return
        scale = version.seniority_scale_id
        if not scale:
            scale = self.env['hr.seniority.scale'].search(
                [('company_id', 'in', (self.company_id.id, False))], limit=1)
        if not scale:
            return
        # Experience as of the end of the payslip period, not "today": a
        # recomputation of a past month must apply that period's percentage.
        years = self.employee_id._get_company_experience_years(self.date_to)
        percent = scale.get_percent(years)
        if percent <= 0:
            return
        monthly_wage = self._get_effective_wage(version) * (version.work_rate or 1.0)
        if monthly_wage <= 0:
            return
        full = monthly_wage * percent / 100.0
        # Пропорція за фактично відпрацьований час (неповний місяць).
        if self.scheduled_days and self.worked_days < self.scheduled_days:
            full = full * self.worked_days / self.scheduled_days
        amount = round(full, 2)
        if amount <= 0:
            return
        self.env['hr.payslip.accrual'].create({
            'payslip_id': self.id,
            'accrual_type_id': acc_type.id,
            'quantity': 1,
            'rate': percent,
            'amount': amount,
            'is_auto_generated': True,
            'notes': _('Вислуга %.1f р. — %.0f%%') % (years, percent),
        })

    def _generate_indexation(self, version, params):
        """Створити авто-нарахування «Індексація» (Закон про індексацію, Порядок №1078).

        Індексується дохід у межах прожиткового мінімуму для працездатних осіб
        на величину приросту наростаючого індексу споживчих цін від базового
        місяця (останнього підвищення зарплати). За неповний місяць — пропорційно
        відпрацьованому часу.
        """
        self.ensure_one()
        if not params:
            return
        if not getattr(version, 'indexation_enabled', False):
            return
        base_month = getattr(version, 'indexation_base_month', False)
        if not base_month:
            return
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'INDEXATION')], limit=1)
        if not acc_type:
            return
        threshold = params.indexation_threshold or 101.0
        percent = self.env['hr.cpi.index'].get_indexation_percent(
            base_month, self.date_to, threshold, self.company_id.id)
        if percent <= 0:
            return
        subsistence = params.subsistence_minimum or 0.0
        if subsistence <= 0:
            return
        # База індексації — дохід у межах ПМ працездатних осіб.
        monthly_wage = self._get_effective_wage(version) * (version.work_rate or 1.0)
        base_amount = min(monthly_wage, subsistence) if monthly_wage else subsistence
        full = base_amount * percent / 100.0
        # Пропорція за фактично відпрацьований час (неповний місяць).
        if self.scheduled_days and self.worked_days < self.scheduled_days:
            full = full * self.worked_days / self.scheduled_days
        amount = round(full, 2)
        if amount <= 0:
            return
        self.env['hr.payslip.accrual'].create({
            'payslip_id': self.id,
            'accrual_type_id': acc_type.id,
            'quantity': 1,
            'rate': percent,
            'amount': amount,
            'is_auto_generated': True,
            'notes': _('Індексація %.1f%% (баз. міс. %s)') % (
                percent, base_month.strftime('%m.%Y')),
        })

    def _base_hourly_rate(self, version, params):
        """Базова годинна ставка для доплат.

        Тарифна сітка — погодинна ставка × коефіцієнт; інакше — місячний
        (з урахуванням work_rate) оклад, поділений на норму годин періоду.
        Не нижче законодавчої мінімальної годинної ставки.
        """
        self.ensure_one()
        min_hourly = (params.min_hourly_wage if params else 0.0) or 0.0
        tariff = getattr(version, 'tariff_grade_id', False)
        if tariff:
            coef = tariff.coefficient or 1.0
            if tariff.hourly_rate:
                rate = tariff.hourly_rate * coef
            elif tariff.min_salary and self.scheduled_hours > 0:
                rate = (tariff.min_salary * coef) / self.scheduled_hours
            else:
                rate = 0.0
        elif self.scheduled_hours > 0:
            monthly = self._get_effective_wage(version) * (version.work_rate or 1.0)
            rate = monthly / self.scheduled_hours
        else:
            rate = 0.0
        return max(rate, min_hourly)

    def _generate_time_surcharges(self, version, params):
        """Створити авто-доплати за нічні/понаднормові/святкові години.

        Доплати рахуються ЗВЕРХУ базового окладу (модель «доплата»):
        - нічні — % годинної ставки (ст. 108 КЗпП, типово 20%);
        - понаднормові — надлишок до подвійного розміру (ст. 106);
        - святкові — надлишок до подвійного розміру (ст. 107).
        """
        self.ensure_one()
        # Для відрядної форми доплати рахуються за середнім заробітком — поза
        # обсягом авто-розрахунку; не нараховуємо з окладної ставки.
        if getattr(version, 'salary_form', 'time') == 'piece':
            return
        hourly = self._base_hourly_rate(version, params)
        if hourly <= 0:
            return
        Accrual = self.env['hr.payslip.accrual']
        AccrualType = self.env['hr.accrual.type']
        night_rate = (params.night_surcharge_rate if params else 20.0) or 0.0
        ot_mult = (params.overtime_multiplier if params else 2.0) or 0.0
        hol_mult = (params.holiday_multiplier if params else 2.0) or 0.0

        surcharges = [
            ('NIGHT', self.night_hours, hourly * night_rate / 100.0,
             _('Доплата за нічні (%.0f%%)') % night_rate),
            ('OVERTIME', self.overtime_hours, hourly * max(ot_mult - 1.0, 0.0),
             _('Понаднормові (×%.2g)') % ot_mult),
            ('HOLIDAY', self.holiday_hours, hourly * max(hol_mult - 1.0, 0.0),
             _('Святкові/неробочі (×%.2g)') % hol_mult),
        ]
        for code, hours, per_hour, note in surcharges:
            if hours <= 0 or per_hour <= 0:
                continue
            acc_type = AccrualType.search([('code', '=', code)], limit=1)
            if not acc_type:
                continue
            amount = round(per_hour * hours, 2)
            if not amount:
                continue
            Accrual.create({
                'payslip_id': self.id,
                'accrual_type_id': acc_type.id,
                'quantity': hours,
                'rate': round(per_hour, 4),
                'amount': amount,
                'is_auto_generated': True,
                'notes': note,
            })

    def _generate_deductions(self):
        """Generate deduction lines.

        Only auto-generated deductions are deleted and recreated.
        Manual deductions added by user are preserved.
        """
        self.ensure_one()
        # Delete only auto-generated deductions, preserve manual ones
        self.deduction_ids.filtered('is_auto_generated').unlink()
        
        # Execution documents, processed in legal order of priority
        # (1 — alimony for minors, 2 — other alimony, 3 — other debts).
        exec_docs = self.env['hr.execution.document'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'active'),
            ('date_from', '<=', self.date_to),
            '|', ('date_to', '>=', self.date_from), ('date_to', '=', False),
        ]).sorted(key=lambda d: (int(d.deduction_priority or '9'), d.date_from))

        alimony_type = self.env['hr.deduction.type'].search([('code', '=', 'ALIMONY')], limit=1)

        # Legal ceiling: total execution-document withholdings may not exceed
        # 50% (or 70% when alimony for minors is involved) of income after taxes.
        net_after_tax = self.gross_salary - self.pdfo_amount - self.military_tax_amount
        cap_percent = max(exec_docs.mapped('max_deduction_percent') or [50.0])
        max_total = net_after_tax * cap_percent / 100
        allocated = 0.0
        params = self.env['hr.psp.parameters'].get_parameters(self.date_to)
        min_wage = params.min_wage if params else 8000

        for doc in exec_docs:
            if doc.calculation_method == 'percent':
                amount = self.gross_salary * doc.percent_value / 100
            elif doc.calculation_method == 'fixed':
                amount = doc.fixed_amount
            else:
                amount = min_wage * doc.percent_value / 100

            # Never collect more than the outstanding debt (finite documents only);
            # the remainder carries over to the next period automatically.
            if doc.total_amount > 0:
                outstanding = doc.total_amount - doc.collected_amount
                amount = min(amount, max(outstanding, 0.0))

            # Enforce the cumulative legal ceiling: lower-priority documents get
            # only what is left under the cap.
            available = max_total - allocated
            amount = min(amount, max(available, 0.0))
            amount = round(amount, 2)
            if amount <= 0:
                continue
            allocated += amount

            self.env['hr.payslip.deduction'].create({
                'payslip_id': self.id,
                'deduction_type_id': alimony_type.id if alimony_type else False,
                'base_amount': self.gross_salary,
                'rate': doc.percent_value if doc.calculation_method == 'percent' else 0,
                'amount': amount,
                'execution_doc_id': doc.id,
                'is_auto_generated': True,
            })

        # Salary advances                                      
        self._generate_advance_deductions()                   


    def _generate_advance_deductions(self):             
        """Generate deduction lines for confirmed salary advances."""
        self.ensure_one()

        advances = self.env['hr.salary.advance'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'confirmed'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            '|',
            ('payslip_id', '=', False),
            ('payslip_id', '=', self.id),
        ], order='date asc, id asc')

        if not advances:
            return

        deduction_type = self.env['hr.deduction.type'].search([
            ('code', '=', 'ADVANCE')
        ], limit=1)

        if not deduction_type:
            return

        for advance in advances:
            self.env['hr.payslip.deduction'].create({
                'payslip_id': self.id,
                'deduction_type_id': deduction_type.id,
                'amount': advance.amount,
                'notes': advance.name,
                'is_auto_generated': True,
            })
            advance.payslip_id = self.id        


    def action_payslip_verify(self):
        self.write({'state': 'verify'})

    def action_payslip_done(self):
        self.write({'state': 'done'})
        advances = self.env['hr.salary.advance'].search([  
            ('payslip_id', 'in', self.ids),                
            ('state', '=', 'confirmed'),                    
        ])                                                  
        if advances:                                      
            advances.write({'state': 'paid'})       

    def action_payslip_cancel(self):
        advances = self.env['hr.salary.advance'].search([  
            ('payslip_id', 'in', self.ids),               
        ])                                                 
        self.write({'state': 'cancel'})
        if advances:                                       
            # Revert to confirmed so advances can be picked up by a reissued payslip.
            advances.write({'state': 'confirmed', 'payslip_id': False})  

    def action_payslip_draft(self):
        self.write({'state': 'draft'})

    def action_print_payslip(self):
        return self.env.ref('l10n_ua_hr_salary.action_report_payslip').report_action(self)

    # ------------------------------------------------------------------
    # Ретро-перерахунки за закриті періоди (#151)
    # ------------------------------------------------------------------
    def _recompute_period_gross(self):
        """Перерахувати валовий дохід періоду з ПОТОЧНИМИ даними.

        Створює тимчасову копію листка (зберігаючи введені вручну нарахування —
        напр. премії), оновлює відпрацьований час із чинного табеля, регенерує
        авто-нарахування за чинними окладом/версією і повертає новий gross.
        Тимчасовий листок одразу видаляється — self не змінюється.
        """
        self.ensure_one()
        temp = self.copy({
            'state': 'draft',
            'payslip_run_id': False,
            'name': _('%s (перерахунок)') % (self.name or ''),
        })
        try:
            temp._compute_working_days()
            temp._generate_accruals()
            # gross_salary — stored compute; читаємо після флашу.
            temp.flush_recordset()
            return temp.gross_salary
        finally:
            temp.unlink()

    def _find_current_draft_payslip(self):
        """Знайти поточний відкритий листок працівника для перенесення дельти."""
        self.ensure_one()
        return self.search([
            ('employee_id', '=', self.employee_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', 'in', ('draft', 'verify')),
            ('date_to', '>', self.date_to),
        ], order='date_to desc', limit=1)

    def action_retro_recalculate(self):
        """Перерахувати закриті періоди й перенести різницю в поточний листок.

        Для кожного обраного закритого (done) листка рахує дельту валового
        доходу відносно сплаченого і, якщо вона ненульова, створює у поточному
        чернетковому листку окремий рядок «Перерахунок за <міс>». ПДФО/ВЗ/ЄСВ
        на дельту перераховуються автоматично в поточному листку. Повторний
        запуск ідемпотентний — попередній ретро-рядок від того ж джерела
        замінюється.
        """
        Retro = self.env['hr.payslip.retro']
        RetroType = self.env['hr.accrual.type'].search(
            [('code', '=', 'RETRO')], limit=1)
        if not RetroType:
            raise UserError(_('Не знайдено тип нарахування «Перерахунок» (RETRO).'))

        changed = 0
        for slip in self:
            if slip.state != 'done':
                raise UserError(_(
                    'Ретро-перерахунок можливий лише для закритих (Done) '
                    'листків. Листок «%s» у стані «%s».') % (slip.name, slip.state))

            target = slip._find_current_draft_payslip()
            if not target:
                raise UserError(_(
                    'Немає поточного відкритого листка для працівника «%s», '
                    'куди перенести різницю. Створіть листок поточного періоду.'
                ) % slip.employee_id.name)

            new_gross = slip._recompute_period_gross()
            delta = round(new_gross - slip.gross_salary, 2)

            # Ідемпотентність: прибрати попередній ретро від цього ж джерела.
            prior = Retro.search([
                ('source_payslip_id', '=', slip.id),
                ('target_payslip_id', '=', target.id),
            ])
            prior.accrual_line_id.unlink()
            prior.unlink()

            if abs(delta) < 0.01:
                continue

            period = slip.date_to.strftime('%m.%Y')
            sign = _('донарахування') if delta > 0 else _('сторнування')
            note = _('Перерахунок за %s (%s): було %.2f, стало %.2f') % (
                period, sign, slip.gross_salary, new_gross)
            line = self.env['hr.payslip.accrual'].create({
                'payslip_id': target.id,
                'accrual_type_id': RetroType.id,
                'quantity': 1,
                'amount': delta,
                'notes': note,
            })
            Retro.create({
                'source_payslip_id': slip.id,
                'target_payslip_id': target.id,
                'accrual_line_id': line.id,
                'old_gross': slip.gross_salary,
                'new_gross': new_gross,
                'gross_delta': delta,
            })
            target.message_post(body=_(
                'Перенесено ретро-різницю %+.2f за період %s (з листка %s).'
            ) % (delta, period, slip.name))
            slip.message_post(body=_(
                'Ретро-перерахунок: різницю %+.2f перенесено в листок %s.'
            ) % (delta, target.name))
            changed += 1

        msg = (_('Перенесено перерахунків: %d.') % changed if changed
               else _('Змін не виявлено — перерахунок не потрібен.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Ретро-перерахунок'), 'message': msg,
                       'type': 'success' if changed else 'info', 'sticky': False},
        }
