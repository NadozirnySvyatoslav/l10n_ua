from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import format_date, float_compare
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
import calendar
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _description = 'Payslip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, employee_id'
    _check_company_auto = True

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
        tracking=True,
        check_company=True,
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
        string='Payslip Batch',
        check_company=True,
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
        compute='_compute_tax_rates', store=True, readonly=False,
        precompute=True,
        help='Rate of the payroll parameters of the payslip company for the '
             'period. Can be corrected by hand.'
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
        compute='_compute_tax_rates', store=True, readonly=False,
        precompute=True,
        help='Rate of the payroll parameters of the payslip company for the '
             'period. Can be corrected by hand.'
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
        compute='_compute_tax_rates', store=True, readonly=False,
        precompute=True,
        help='Rate of the payroll parameters of the payslip company for the '
             'period. Can be corrected by hand.'
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
        """Clear employee and batch if from a different company (preserve shared employees)."""
        if self.employee_id and self.employee_id.company_id \
                and self.employee_id.company_id != self.company_id:
            self.employee_id = False
        if self.payslip_run_id and self.payslip_run_id.company_id != self.company_id:
            self.payslip_run_id = False

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
            params = self.env['hr.psp.parameters'].get_parameters(
                payslip.date_to, payslip.company_id.id)
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
            params = self.env['hr.psp.parameters'].get_parameters(
                payslip.date_to, payslip.company_id.id)
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
                if params:
                    payslip.esv_base = min(
                        max(esv_taxable, params.min_wage), params.max_esv_base)
                else:
                    # No parameters for the period, so no statutory floor or
                    # ceiling to apply. Such a payslip can be neither computed
                    # nor verified: see _check_psp_parameters_known.
                    payslip.esv_base = esv_taxable
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

    def _daily_hour_norm(self, version=None):
        """Денна норма годин з урахуванням ставки зайнятості (work_rate).

        0.5 ставки → 4 год/день при 8-годинному дні. Базова денна норма —
        з графіка/тижневої норми версії, помножена на work_rate. Так табель
        неповного робочого часу відображає пропорційно зменшену норму, а не
        фіксовані 8 год (#149).

        The version is named when the norm is needed for a particular day:
        the work rate may change inside the month, and then every day has a
        norm of its own. Defaults to the version of the payslip.
        """
        self.ensure_one()
        version = version if version is not None else self.version_id
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

        # The norm is the month's, never the employee's: the timesheet below
        # brings what was worked, not what was due.
        self.scheduled_days, self.scheduled_hours = self._l10n_ua_month_norm()

        # get amount of working days from timesheet
        ts_line = self._timesheet_line()
        if ts_line and self._covers_whole_month():
            self.worked_days = ts_line.worked_days
            self.worked_hours = ts_line.worked_hours
            # Відхилення для авто-доплат (нічні/понаднормові/святкові).
            self.night_hours = ts_line.night_hours
            self.overtime_hours = ts_line.overtime_hours
            self.holiday_hours = getattr(ts_line, 'holiday_hours', 0.0)
        elif ts_line:
            # A payslip for a part of the month reads the days of that part
            # only: the sheet covers the whole month, and two payslips that
            # split it would otherwise both pay all of it.
            days = self._timesheet_days(ts_line)
            self.worked_days = len(days.filtered(lambda d: d.code_id.is_worked))
            self.worked_hours = sum(days.mapped('hours'))
            self.night_hours = sum(days.mapped('night_hours'))
            self.overtime_hours = sum(days.mapped('overtime_hours'))
            self.holiday_hours = sum(days.filtered(
                lambda d: d.code_id.code_type == 'holiday').mapped('hours'))
        if ts_line:
            return

        # default if there is no timesheets: the working days of the norm the
        # employee was not away on — a day of time off is paid by its own
        # line, not by the salary.
        worked, worked_hours = 0, 0.0
        away = self._absence_dates()
        working = self._working_dates(self.date_from, self.date_to)
        curr = self.date_from
        while curr <= self.date_to:
            if curr in working and curr not in away:
                worked += 1
                worked_hours += self._daily_hour_norm(self._version_on(curr))
            curr += relativedelta(days=1)
        self.worked_days = worked
        self.worked_hours = worked_hours

    def _l10n_ua_month_norm(self):
        """The working time norm of the month of the period end: (days, hours).

        The norm of the month itself, the same for everyone in the company:
        an absence, a hire in the middle of the month, a part-time rate or a
        shift schedule does not shorten it. Each day is read the way the
        timesheet generator reads it: from the production calendar when the
        company keeps one for the year and has the day in it, otherwise
        Monday to Friday. The calendar is optional on purpose — under martial
        law public holidays are working days, and an empty calendar is a
        valid setup, not a missing one.

        The hours of a day are those of a full-time day of the company's
        working schedule, 8 when it has none.
        """
        self.ensure_one()
        month_start = self.date_to.replace(day=1)
        working = self._working_dates(
            month_start, month_start + relativedelta(months=1, days=-1))
        return len(working), sum(working.values())

    def _working_dates(self, date_from, date_to):
        """{date: full-time hours} of the working days between the two dates.

        From the production calendar when the company keeps one for the year
        and has the day in it, read by the type of the day as the timesheet
        generator reads it; otherwise Monday to Friday at the full-time day
        of the company's working schedule.
        """
        self.ensure_one()
        day_hours = self.company_id.resource_calendar_id.hours_per_day or 8.0
        calendar_days = {}
        # The production calendar comes with the attendance sheet module,
        # which this one does not depend on.
        if 'hr.production.calendar' in self.env:
            productions = self.env['hr.production.calendar'].search([
                ('year', 'in', list(range(date_from.year, date_to.year + 1))),
                ('company_id', '=', self.company_id.id),
            ])
            calendar_days = {
                line.date: line for line in productions.line_ids
                if date_from <= line.date <= date_to
            }
        working, current = {}, date_from
        while current <= date_to:
            line = calendar_days.get(current)
            if line is not None:
                if line.day_type not in ('holiday', 'weekend'):
                    working[current] = line.working_hours or day_hours
            elif current.weekday() < 5:
                working[current] = day_hours
            current += relativedelta(days=1)
        return working

    def _timesheet_line(self):
        """The confirmed timesheet line of this employee for the month.

        The hours of the payslip come from it, and so does the day each of
        them was worked on, which is what a rate changing inside the month is
        paid by. `None` when the attendance sheet module is not installed or
        the month has no confirmed sheet.
        """
        self.ensure_one()
        if 'hr.timesheet.line' not in self.env or not self.date_to:
            return None
        return self.env['hr.timesheet.line'].search([
            ('employee_id', '=', self.employee_id.id),
            ('timesheet_id.month', '=', str(self.date_to.month)),
            ('timesheet_id.year', '=', self.date_to.year),
            ('timesheet_id.state', 'in', ['confirmed', 'approved'])
        ], limit=1, order='timesheet_id desc') or None

    def _covers_whole_month(self):
        """Whether the period is exactly the calendar month of its end."""
        self.ensure_one()
        month_start = self.date_to.replace(day=1)
        return self.date_from == month_start and \
            self.date_to == month_start + relativedelta(months=1, days=-1)

    def _timesheet_days(self, line):
        """The day rows of the sheet that fall inside the period."""
        self.ensure_one()
        return line.day_ids.filtered(
            lambda d: d.date and self.date_from <= d.date <= self.date_to)

    def _version_on(self, day):
        """The version in force on that day, by the rule of the payslip.

        The same filter `_compute_version_id` uses to pick the version of the
        payslip, only asked about a day instead of the start of the period —
        so the payslip and the day-by-day reading never disagree about what a
        version is. Falls back to the version of the payslip.
        """
        self.ensure_one()
        versions = self.employee_id.version_ids.filtered(
            lambda v: v.date_version <= day and v.contract_date_start
        ).sorted('date_version', reverse=True)
        return versions[0] if versions else self.version_id

    def _version_periods(self):
        """[(version, date_from, date_to)] over the period of the payslip.

        One entry when nothing changed, which is the usual month. The payslip
        keeps its single `version_id`: these periods live inside the
        calculation and are not stored anywhere.
        """
        self.ensure_one()
        versions = self.employee_id.version_ids.filtered(
            lambda v: v.date_version <= self.date_to and v.contract_date_start
        ).sorted('date_version')
        periods = []
        for index, version in enumerate(versions):
            start = max(version.date_version, self.date_from)
            end = self.date_to
            if index + 1 < len(versions):
                end = min(end, versions[index + 1].date_version
                          - relativedelta(days=1))
            if start <= end:
                periods.append((version, start, end))
        return periods or [(self.version_id, self.date_from, self.date_to)]

    def _check_uniform_period(self, periods):
        """Refuse a period whose versions a single payslip cannot hold.

        Three things exist once on a payslip and cannot be told apart by the
        day: the currency the salary is denominated in (with its rate), the
        Diia.City status that sets the tax rates, and the company. Taking the
        version at the end of the period for them would understate pay by the
        exchange rate or the tax by thirteen points, and nothing on the
        payslip would say so. Two periods, two payslips.
        """
        self.ensure_one()
        versions = [version for version, _start, _end in periods if version]
        if len(set(versions)) < 2:
            return
        if len({version.salary_currency_id for version in versions}) > 1:
            raise UserError(_(
                'The period of %(employee)s holds versions with different '
                'salary currencies. A payslip states one currency and one '
                'rate, so split it into a payslip per period.',
                employee=self.employee_id.name))
        if len({bool(version.diia_city_employee)
                or version.contract_type_ua == 'gig' for version in versions}) > 1:
            raise UserError(_(
                'The Diia.City status of %(employee)s changes inside this '
                'period, and with it the rate of the personal income tax. A '
                'payslip is taxed at one rate, so split it into a payslip per '
                'period.', employee=self.employee_id.name))
        if len({version.company_id for version in versions}) > 1:
            raise UserError(_(
                'The period of %(employee)s holds versions of different '
                'companies. Split it into a payslip per company.',
                employee=self.employee_id.name))

    def _worked_days_detail(self):
        """The days this payslip pays for.

        (date, hours, night, overtime, holiday, worked), where `worked` is 1
        for a day that counts as a worked day. From the timesheet when there
        is one — the day rows of the period, counted the way the sheet counts
        them: every hour into `worked_hours`, but only a day whose code is a
        worked one into `worked_days`. A Saturday worked on a day-off code
        brings its hours and its holiday surcharge, not a day of salary.
        Without a sheet, the working days of the period at the daily norm of
        the version in force that day. Days with nothing on them are left
        out: they are paid nothing and would only ask for a rate on a day
        nobody worked.
        """
        self.ensure_one()
        line = self._timesheet_line()
        if line:
            days = [
                (day.date, day.hours, day.night_hours, day.overtime_hours,
                 day.hours if day.code_id.code_type == 'holiday' else 0.0,
                 1 if day.code_id.is_worked else 0)
                for day in self._timesheet_days(line).sorted('date')
            ]
            return [day for day in days if any(day[1:])]
        days, current = [], self.date_from
        away = self._absence_dates()
        working = self._working_dates(self.date_from, self.date_to) \
            if self.date_from and self.date_to else {}
        while current and self.date_to and current <= self.date_to:
            if current in working and current not in away:
                days.append((current, self._daily_hour_norm(
                    self._version_on(current)), 0.0, 0.0, 0.0, 1))
            current += relativedelta(days=1)
        return days

    def _pay_segments(self):
        """The parts of the period that are paid alike, day by day.

        A day is paid by what was in force on it: its version, the tariff
        grade period of that version, and the salary that answers for it —
        the wage of the version, or the staffing line of that day when the
        version carries none. Days whose three answers coincide form one
        segment, so a month where nothing changed stays a single line and a
        version created for a phone number does not split anything.

        The days are the very ones `worked_hours` and `worked_days` are made
        of, so the hours and the worked days of the segments add up to the
        figures on the payslip exactly — nothing is averaged and nothing is
        apportioned.

        Returns an empty list when they do not add up, and the caller pays the
        period as one, as before. The button recomputes the hours from the
        sheet first, so this is a safeguard rather than a feature: it holds
        for a payslip whose figures were written by other means, which no day
        carries and which there is therefore nothing to place on a date.
        """
        self.ensure_one()
        # Before the hours: a period a payslip cannot hold is refused whether
        # or not its days happen to add up.
        self._check_uniform_period(self._version_periods())
        days = self._worked_days_detail()
        if float_compare(sum(day[1] for day in days), self.worked_hours,
                         precision_digits=2) != 0 \
                or sum(day[5] for day in days) != self.worked_days:
            return []
        segments, wages, grades, keys, order = {}, {}, {}, {}, []
        for day, hours, night, overtime, holiday, worked in days:
            version = self._version_on(day)
            if version not in grades:
                grades[version] = self.env['hr.tariff.grade'].search([
                    ('company_id', '=', version.tariff_grade_id.company_id.id),
                    ('grade', '=', version.tariff_grade_id.grade),
                ], order='date_from') if version.tariff_grade_id \
                    else self.env['hr.tariff.grade']
            tariff = next(
                (period for period in grades[version]
                 if period.date_from <= day
                 and (not period.date_to or period.date_to >= day)), None)
            if version.tariff_grade_id and tariff is None:
                self._check_tariff_rate(
                    version, self.env['hr.tariff.grade'], day)
            # The wage of a version is one figure; only a version without one
            # asks the staffing table, and then the answer may change by the
            # day, so it is read per day and remembered.
            if version.wage:
                wage = self._get_effective_wage(version)
            else:
                if (version, day) not in wages:
                    wages[(version, day)] = self._get_effective_wage(version, day)
                wage = wages[(version, day)]
            if version not in keys:
                keys[version] = self._version_pay_key(version)
            # On a tariff grade the salary is paid by the hour, and the wage
            # is read only by the seniority and indexation bases; where
            # nothing reads it, it does not split anything either.
            wage_matters = (not version.tariff_grade_id
                            or getattr(version, 'seniority_enabled', False)
                            or getattr(version, 'indexation_enabled', False))
            # Not the version itself: two versions that pay alike — and Odoo
            # writes one for any change of the card — must not split the month.
            key = (keys[version], tariff.id if tariff else 0,
                   round(wage, 2) if wage_matters else 0.0)
            segment = segments.setdefault(key, {
                'version': version, 'grade': tariff, 'wage': wage,
                'hours': 0.0, 'days': 0, 'night': 0.0, 'overtime': 0.0,
                'holiday': 0.0, 'date_from': day, 'date_to': day, 'runs': [],
            })
            segment['hours'] += hours
            segment['days'] += worked
            segment['night'] += night
            segment['overtime'] += overtime
            segment['holiday'] += holiday
            segment['date_from'] = min(segment['date_from'], day)
            segment['date_to'] = max(segment['date_to'], day)
            order.append((day, key))
        # The stretches of days each segment covers, broken wherever a day of
        # another segment stands between: two versions that pay alike merge
        # into one segment even when a third one lies between them, and the
        # note must not claim the days of that third one.
        previous = None
        for day, key in order:
            runs = segments[key]['runs']
            if key == previous:
                runs[-1][1] = day
            else:
                runs.append([day, day])
            previous = key
        return sorted(segments.values(), key=lambda segment: segment['date_from'])

    def _segment_weights(self, segments):
        """The share of the month each segment stands for.

        The month is shared out between the segments by their worked days, so
        the shares add up to exactly one: a month split between two versions
        pays one allowance, not two, and never more than one. A single segment
        has a share of exactly 1.0, so whatever is multiplied by it comes out
        bit for bit as it did before there were segments. Segments of hours
        only (work on days off) are weighted by their hours.
        """
        self.ensure_one()
        days = [segment['days'] for segment in segments]
        if sum(days):
            return [count / sum(days) for count in days]
        hours = [segment['hours'] for segment in segments]
        if sum(hours):
            return [count / sum(hours) for count in hours]
        return [1.0] + [0.0] * (len(segments) - 1)

    def _rounded_parts(self, amounts, rounding):
        """Round the parts of one whole so they add up to the whole rounded once.

        Each part is the difference between the rounded running totals, so a
        month split in two loses no kopiyka to rounding each half on its own.
        A single part is the amount rounded, exactly as before there were
        parts. `rounding` is the rounding the accrual always had.
        """
        parts, paid, running = [], 0.0, 0.0
        for amount in amounts:
            running += amount
            part = rounding(rounding(running) - paid)
            parts.append(part)
            paid = rounding(paid + part)
        return parts

    def _version_pay_key(self, version):
        """Everything in a version that a payslip pays by.

        Two versions with the same key are paid alike, so their days make one
        segment. The grade and the salary are not here: they are asked about
        the day, and stand beside this key.
        """
        self.ensure_one()
        return (
            round(version.work_rate or 1.0, 4),
            getattr(version, 'salary_form', 'time'),
            tuple(sorted(
                (allowance.allowance_type_id.id,
                 round(allowance._l10n_ua_amount_at(
                     self.date_to, rate=self.salary_rate), 2))
                for allowance in version.allowance_ids.filtered('is_active'))),
            bool(getattr(version, 'seniority_enabled', False)),
            version.seniority_scale_id.id
            if 'seniority_scale_id' in version._fields else 0,
            bool(getattr(version, 'indexation_enabled', False)),
            getattr(version, 'indexation_base_month', False),
        )

    def _whole_period_segment(self):
        """The period as one segment, the way it was paid before segments."""
        self.ensure_one()
        version = self.version_id
        return {
            'version': version,
            'grade': version.tariff_grade_id._l10n_ua_grade_on(self.date_to)
            if version.tariff_grade_id else self.env['hr.tariff.grade'],
            'wage': self._get_effective_wage(version),
            'hours': self.worked_hours, 'days': self.worked_days,
            'night': self.night_hours, 'overtime': self.overtime_hours,
            'holiday': self.holiday_hours,
            'date_from': self.date_from, 'date_to': self.date_to,
            'runs': [[self.date_from, self.date_to]],
        }

    def _segment_note(self, note, segment, several, versions):
        """A note that says which days, and whose version, it is about."""
        if not several:
            return note
        dates = ', '.join(
            _('%(date_from)s – %(date_to)s',
              date_from=format_date(self.env, start),
              date_to=format_date(self.env, end))
            for start, end in segment['runs'])
        if versions:
            dates = _('version of %(version)s, %(dates)s',
                      version=format_date(
                          self.env, segment['version'].date_version),
                      dates=dates)
        return _('%(note)s, %(rest)s', note=note, rest=dates) if note else dates

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

    @api.depends('company_id', 'date_to')
    def _compute_tax_rates(self):
        """Tax rates of the company's payroll parameters for the period.

        The rates used to be constants of the payslip itself, so the rates of
        the parameters were read nowhere and changing them changed nothing.
        A payslip that is no longer a draft keeps the rates it was computed
        with; without parameters the rates stay at zero, and the payslip can
        be neither computed nor verified (see _check_psp_parameters_known).
        """
        Params = self.env['hr.psp.parameters']
        for payslip in self:
            if payslip.state != 'draft':
                continue
            params = Params.get_parameters(
                payslip.date_to, payslip.company_id.id) \
                if payslip.date_to and payslip.company_id else None
            payslip.pdfo_rate = params.pdfo_rate if params else 0.0
            payslip.military_tax_rate = params.military_tax_rate if params else 0.0
            payslip.esv_rate = params.esv_rate if params else 0.0

    def _check_psp_parameters_known(self, params):
        """Refuse to compute a payslip without payroll parameters.

        Without them the sheet used to fall back to constants hardcoded years
        ago (minimum wage, ESV base limits, minimum hourly wage) and looked
        perfectly normal, so nobody noticed the stale numbers.
        """
        self.ensure_one()
        if not params:
            raise UserError(_(
                'No payroll parameters are defined for company "%(company)s" '
                'on %(date)s. Add them in Payroll → Configuration → PSP Parameters '
                'before computing payslips.',
                company=self.company_id.display_name,
                date=format_date(self.env, self.date_to)))

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

    def _get_effective_wage(self, version, on_date=None):
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
        version already stands on (`_compute_version_id`), unless a day is
        named: the accrual engine asks about each day of its own, so a
        staffing line approved in the middle of a month pays from the day it
        starts, exactly as a version does.

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
            anchor = on_date or self.date_from or fields.Date.context_today(self)
            staffing = self.env['hr.staffing.table'].with_company(
                version.company_id)._resolve(
                    version.company_id, version.department_id,
                    version.job_id, anchor)
            if staffing.salary:
                return staffing._salary_in_company_currency(anchor)

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

        salary_type = self.env['hr.accrual.type'].search([('code', '=', 'SALARY')], limit=1)
        params = self.env['hr.psp.parameters'].get_parameters(
            self.date_to, self.company_id.id)
        self._check_psp_parameters_known(params)

        # Every part of the period is paid by what was in force on its days:
        # its version, its tariff period, its staffing line.
        segments = self._pay_segments() or [self._whole_period_segment()]
        several = len(segments) > 1
        versions = len({segment['version'] for segment in segments}) > 1
        total_days = sum(segment['days'] for segment in segments)

        # If the user already entered a base-wage accrual by hand, don't add the
        # version-based one on top — that would double-count the salary.
        has_manual_salary = salary_type and any(
            a.accrual_type_id == salary_type and not a.is_auto_generated
            for a in self.accrual_ids
        )

        for segment in segments:
            version = segment['version']
            # Форма оплати праці: відрядна замінює окладну/тарифну (#143).
            if getattr(version, 'salary_form', 'time') == 'piece':
                self._generate_piece_work(version, params, segment)
                continue
            if not salary_type or has_manual_salary:
                continue
            # tariff grade calculations
            if version.tariff_grade_id:
                if segment['hours'] > 0:
                    tariff = segment['grade']
                    self._check_tariff_rate(version, tariff, segment['date_from'])
                    # The grade rate is final: the progression is already in
                    # it. Floor — never below the statutory minimum hourly
                    # wage, which is a minimum per hour and so holds for each
                    # part of the period on its own.
                    hourly_rate = max(tariff.hourly_rate, params.min_hourly_wage)
                    if hourly_rate > 0:
                        self.env['hr.payslip.accrual'].create({
                            'payslip_id': self.id,
                            'accrual_type_id': salary_type.id,
                            'quantity': segment['hours'],
                            'rate': hourly_rate,
                            'amount': round(hourly_rate * segment['hours'], 2),
                            'is_auto_generated': True,
                            'notes': self._segment_note(
                                _('Tariff: %s', tariff.name), segment,
                                several, versions),
                       })

            # monthly wage calculation
            else:
                # Ставка зайнятості (work_rate): 0.5 ставки → половина окладу.
                # Тарифний (погодинний) шлях цього не потребує — там
                # пропорційність дають фактично відпрацьовані години.
                monthly_wage = segment['wage'] * (version.work_rate or 1.0)
                if monthly_wage and self.scheduled_days > 0:
                    # scheduled_days - number of expected working days in the months
                    daily_rate = monthly_wage / self.scheduled_days
                    if not several and self.worked_days >= self.scheduled_days:
                        amount = monthly_wage  # full (rate-adjusted) amount if worked all days
                    else:
                        # More worked days than scheduled never pay more than
                        # the month: the same ceiling the single segment has
                        # just above, shared out between the segments.
                        amount = daily_rate * segment['days'] * min(
                            1.0, self.scheduled_days / max(total_days, 1))

                    self.env['hr.payslip.accrual'].create({
                        'payslip_id': self.id,
                        'accrual_type_id': salary_type.id,
                        'quantity': segment['days'],
                        'rate': daily_rate,
                        'amount': round(amount, 2),
                        'is_auto_generated': True,
                        'notes': self._segment_note(
                            '', segment, several, versions) or False,
                    })

        self._generate_allowances(segments, several, versions)

        # Авто-доплати за відхилення в табелі (нічні/понаднормові/святкові) — #143.
        self._generate_time_surcharges(segments, params, several, versions)

        # Індексація заробітної плати — #138.
        self._generate_indexation(segments, params, several, versions)

        # Надбавка за вислугу років — #143.
        self._generate_seniority(segments, params, several, versions)

        # The norm is the month's, so the salary pays only the days worked;
        # the days away are paid by what pays for them.
        self._generate_absence_pay()

    def _generate_absence_pay(self):
        """Accrue the pay of the absences that fall in the period.

        The salary pays the days worked against the norm of the month, so a
        day away is paid by its own line: a vacation day at the average daily
        salary of its time off, a sick day at the daily rate of its
        certificate — the first `employer_days` by the employer, the rest by
        the fund — and a maternity day by the maternity benefit. The rates are
        the ones the time off and the certificate already calculate; this only
        places their days in the payslip of the month each day falls in, so an
        absence across two months is paid by both.

        A type entered by hand on the payslip is left to it, as the salary
        is. An absence that cannot be paid stops the calculation instead of
        leaving its days unpaid without a word.

        Absences come from `l10n_ua_hr_holidays`, which this module does not
        require: without it there is nothing to read.
        """
        self.ensure_one()
        if 'hr.sick.leave' not in self.env:
            return
        Type = self.env['hr.accrual.type']
        salary = Type.search([('code', '=', 'SALARY')], limit=1)
        if salary and any(line.accrual_type_id == salary and not line.is_auto_generated
                          for line in self.accrual_ids):
            # A salary entered by hand says itself which days it pays for;
            # the absences are left to whoever entered it, as before.
            return
        kinds = {code: Type.search([('code', '=', code)], limit=1)
                 for code in ('VACATION', 'SICK_EMP', 'SICK_FSS', 'MATERNITY')}
        manual = {line.accrual_type_id for line in self.accrual_ids
                  if not line.is_auto_generated}

        def accrue(code, days, rate, note):
            kind = kinds[code]
            if not kind or kind in manual or not days or not rate:
                return
            self.env['hr.payslip.accrual'].create({
                'payslip_id': self.id,
                'accrual_type_id': kind.id,
                'quantity': days,
                'rate': rate,
                'amount': round(rate * days, 2),
                'is_auto_generated': True,
                'notes': note,
            })

        certificates = self.env['hr.sick.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('confirmed', 'paid')),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ], order='date_from')
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', self.date_to),
            ('request_date_to', '>=', self.date_from),
        ], order='request_date_from')
        holidays = self._public_holiday_dates()
        # Days the timesheet has as worked are paid by the salary already;
        # paying them as an absence too would pay them twice.
        line = self._timesheet_line()
        worked = {day.date for day in self._timesheet_days(line)
                  if day.code_id.is_worked} if line else set()

        def check_not_worked(dates, document):
            clash = sorted(worked & dates)
            if clash:
                raise UserError(_(
                    'The timesheet of %(employee)s has %(dates)s as worked, '
                    'but they fall on %(document)s. Correct the timesheet or '
                    'the absence.',
                    employee=self.employee_id.name,
                    dates=', '.join(format_date(self.env, day) for day in clash),
                    document=document))

        for leave in leaves:
            category = leave.holiday_status_id.ua_leave_category
            if category in ('sick', 'maternity'):
                # Paid by its certificate below; without one there is nothing
                # to pay it by.
                if not (leave.sick_leave_id & certificates
                        or certificates.filtered(lambda c: c.leave_id == leave)):
                    raise UserError(_(
                        'The time off "%(leave)s" of %(employee)s has no '
                        'confirmed sick-leave certificate, so its days cannot '
                        'be paid. Enter and confirm the certificate in Sick '
                        'Leaves.',
                        leave=leave.display_name,
                        employee=self.employee_id.name))
                continue
            if not leave.holiday_status_id.is_paid or category in ('childcare', 'unpaid') \
                    or leave.holiday_status_id.request_unit != 'day':
                continue
            if not category:
                # Without it, a paid sickness or maternity leave would be paid
                # as a vacation.
                raise UserError(_(
                    'The time off type "%(type)s" has no Ukrainian leave '
                    'category, so the time off "%(leave)s" of %(employee)s '
                    'cannot be paid. Set the category on the time off type.',
                    type=leave.holiday_status_id.display_name,
                    leave=leave.display_name,
                    employee=self.employee_id.name))
            # The days of the time off in the period, less the public holidays
            # — the same list its length is reduced by.
            first = max(leave.request_date_from, self.date_from)
            last = min(leave.request_date_to, self.date_to)
            dates = {first + relativedelta(days=n)
                     for n in range((last - first).days + 1)} - holidays
            if not dates:
                continue
            check_not_worked(dates, leave.display_name)
            days = len(dates)
            # Fixed when the time off is first paid, so both months of one
            # across them are paid at the same rate.
            if not leave.average_daily_salary:
                leave.sudo().average_daily_salary = leave._calculate_average_salary()
            if not leave.average_daily_salary:
                raise UserError(_(
                    'No average daily salary could be determined for the time '
                    'off "%(leave)s" of %(employee)s. Enter it on the time off.',
                    leave=leave.display_name,
                    employee=self.employee_id.name))
            accrue('VACATION', days, leave.average_daily_salary, leave.display_name)

        for certificate in certificates:
            if not certificate.average_daily_salary:
                certificate.sudo().action_calculate()
            if not certificate.average_daily_salary:
                raise UserError(_(
                    'No average daily salary could be determined for the sick '
                    'leave %(certificate)s of %(employee)s. Enter it on the '
                    'certificate.',
                    certificate=certificate.name,
                    employee=self.employee_id.name))
            rate = certificate.average_daily_salary * certificate.payment_percent / 100
            check_not_worked({
                certificate.date_from + relativedelta(days=n)
                for n in range((certificate.date_to - certificate.date_from).days + 1)
            }, certificate.name)
            employer = fund = 0
            for n in range((certificate.date_to - certificate.date_from).days + 1):
                day = certificate.date_from + relativedelta(days=n)
                if self.date_from <= day <= self.date_to:
                    if n < certificate.employer_days:
                        employer += 1
                    else:
                        fund += 1
            accrue('SICK_EMP', employer, rate, certificate.name)
            accrue('MATERNITY' if certificate.sick_leave_type == 'pregnancy'
                   else 'SICK_FSS', fund, rate, certificate.name)

    def _absence_dates(self):
        """The days of the period the employee was away on a validated time off
        counted in days, or on a confirmed sick-leave certificate.

        A public holiday inside a time off is not part of it — the time off is
        shortened by it and does not pay it — so it is not a day away either.
        It is left to the source of the norm: where the production calendar
        marks it a holiday, it is out of the norm and out of the days worked
        alike, and the salary is not reduced for it. Without a calendar that
        knows it, the norm counts it as a working day, and so does the
        fallback, rather than leave a day of the norm paid by nothing. A
        sickness runs in calendar days, holidays included.
        """
        self.ensure_one()
        if 'hr.sick.leave' not in self.env or not (self.date_from and self.date_to):
            return set()

        def days_of(records, first_field, last_field):
            dates = set()
            for record in records:
                current = max(record[first_field], self.date_from)
                while current <= min(record[last_field], self.date_to):
                    dates.add(current)
                    current += relativedelta(days=1)
            return dates

        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'validate'),
            ('holiday_status_id.request_unit', '=', 'day'),
            ('request_date_from', '<=', self.date_to),
            ('request_date_to', '>=', self.date_from),
        ])
        certificates = self.env['hr.sick.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('confirmed', 'paid')),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ])
        return (days_of(leaves, 'request_date_from', 'request_date_to')
                - self._public_holiday_dates()) \
            | days_of(certificates, 'date_from', 'date_to')

    def _public_holiday_dates(self):
        """The public holidays of the period, from the list time off is
        shortened by."""
        self.ensure_one()
        found = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', datetime.combine(self.date_to, time.max)),
            ('date_to', '>=', datetime.combine(self.date_from, time.min)),
        ])
        dates = set()
        for holiday in found:
            current = max(holiday.date_from.date(), self.date_from)
            while current <= min(holiday.date_to.date(), self.date_to):
                dates.add(current)
                current += relativedelta(days=1)
        return dates

    def _generate_allowances(self, segments, several, versions):
        """The allowances of each version, shared out by the days of its segment.

        A month with one segment pays every allowance whole, whatever was
        worked — as allowances always were. A month split between versions
        pays each version's allowances for its share of the worked days, so
        the parts add up to one month and never to more. Whether an allowance
        should shrink for days not worked is a separate question this does
        not answer.

        The same allowance in successive versions — the n-th allowance of a
        type in each — is rounded as one whole, so splitting it loses no
        kopiyka.
        """
        self.ensure_one()
        allowance_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'ALLOWANCE')], limit=1)
        if not allowance_type:
            return
        groups = defaultdict(list)
        for segment, share in zip(segments, self._segment_weights(segments)):
            by_type = defaultdict(list)
            for allowance in segment['version'].allowance_ids.filtered(
                    'is_active').sorted('id'):
                by_type[allowance.allowance_type_id].append(allowance)
            for kind, allowances in by_type.items():
                for index, allowance in enumerate(allowances):
                    # Не збережене `calculated_amount`, а сума за курсом
                    # цього листка: воно пораховане на дату початку надбавки,
                    # і для відсотка від валютного окладу це курс, якому може
                    # бути рік. Курс передаємо свій, а не дату, бо `salary_rate`
                    # бухгалтер може виправити руками — інакше оклад пішов би
                    # за виправленим курсом, а надбавка до нього за
                    # довідниковим.
                    exact = allowance._l10n_ua_amount_at(
                        self.date_to, rate=self.salary_rate) * share
                    groups[(kind.id, index)].append((segment, allowance, exact))
        # The amount field rounds by the currency, so the parts do too.
        rounding = self.company_id.currency_id.round
        for entries in groups.values():
            parts = self._rounded_parts([entry[2] for entry in entries], rounding)
            for (segment, allowance, _exact), amount in zip(entries, parts):
                if several and not amount:
                    continue
                self.env['hr.payslip.accrual'].create({
                    'payslip_id': self.id,
                    'accrual_type_id': allowance_type.id,
                    'quantity': 1,
                    'amount': amount,
                    'notes': self._segment_note(
                        allowance.allowance_type_id.name, segment,
                        several, versions),
                    'is_auto_generated': True,
                })

    def _generate_piece_work(self, version, params, segment=None):
        """Створити авто-нарахування «Відрядна оплата» за нарядами періоду.

        Підсумовує наряди відрядної оплати (hr.piece.work.entry) працівника,
        дата яких потрапляє в період нарахування, у єдине нарахування PIECE.

        An entry carries a date, so when only a part of the month was paid by
        the piece, the entries of its days are the ones taken.
        """
        self.ensure_one()
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'PIECE')], limit=1)
        if not acc_type:
            return
        date_from = segment['date_from'] if segment else self.date_from
        date_to = segment['date_to'] if segment else self.date_to
        entries = self.env['hr.piece.work.entry'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
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

    def _generate_seniority(self, segments, params, several=False, versions=False):
        """Створити авто-надбавку «За вислугу років» на основі стажу.

        Відсоток надбавки береться зі ступінчастої шкали (hr.seniority.scale)
        за стажем роботи в компанії. База — посадовий оклад (з урахуванням
        ставки зайнятості), пропорційно відпрацьованому часу.
        """
        self.ensure_one()
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'SENIORITY')], limit=1)
        if not acc_type:
            return
        # Experience as of the end of the payslip period, not "today": a
        # recomputation of a past month must apply that period's percentage.
        years = self.employee_id._get_company_experience_years(self.date_to)
        worked = sum(segment['days'] for segment in segments)
        entries = []
        for segment, share in zip(segments, self._segment_weights(segments)):
            version = segment['version']
            if not getattr(version, 'seniority_enabled', False):
                continue
            scale = version.seniority_scale_id
            if not scale:
                scale = self.env['hr.seniority.scale'].search(
                    [('company_id', 'in', (self.company_id.id, False))], limit=1)
            if not scale:
                continue
            percent = scale.get_percent(years)
            if percent <= 0:
                continue
            monthly_wage = segment['wage'] * (version.work_rate or 1.0)
            if monthly_wage <= 0:
                continue
            full = monthly_wage * percent / 100.0
            # Пропорція за фактично відпрацьований час (неповний місяць).
            if self.scheduled_days and worked < self.scheduled_days:
                full = full * worked / self.scheduled_days
            # The part of it this segment pays.
            entries.append((segment, percent, full * share))
        parts = self._rounded_parts(
            [entry[2] for entry in entries], lambda value: round(value, 2))
        for (segment, percent, _exact), amount in zip(entries, parts):
            if amount <= 0:
                continue
            self.env['hr.payslip.accrual'].create({
                'payslip_id': self.id,
                'accrual_type_id': acc_type.id,
                'quantity': 1,
                'rate': percent,
                'amount': amount,
                'is_auto_generated': True,
                'notes': self._segment_note(
                    _('Вислуга %.1f р. — %.0f%%') % (years, percent),
                    segment, several, versions),
            })

    def _generate_indexation(self, segments, params, several=False, versions=False):
        """Створити авто-нарахування «Індексація» (Закон про індексацію, Порядок №1078).

        Індексується дохід у межах прожиткового мінімуму для працездатних осіб
        на величину приросту наростаючого індексу споживчих цін від базового
        місяця (останнього підвищення зарплати). За неповний місяць — пропорційно
        відпрацьованому часу.
        """
        self.ensure_one()
        if not params:
            return
        acc_type = self.env['hr.accrual.type'].search(
            [('code', '=', 'INDEXATION')], limit=1)
        if not acc_type:
            return
        subsistence = params.subsistence_minimum or 0.0
        if subsistence <= 0:
            return
        threshold = params.indexation_threshold or 101.0
        worked = sum(segment['days'] for segment in segments)
        entries = []
        for segment, share in zip(segments, self._segment_weights(segments)):
            version = segment['version']
            if not getattr(version, 'indexation_enabled', False):
                continue
            base_month = getattr(version, 'indexation_base_month', False)
            if not base_month:
                continue
            percent = self.env['hr.cpi.index'].get_indexation_percent(
                base_month, self.date_to, threshold, self.company_id.id)
            if percent <= 0:
                continue
            # База індексації — дохід у межах ПМ працездатних осіб.
            monthly_wage = segment['wage'] * (version.work_rate or 1.0)
            base_amount = min(monthly_wage, subsistence) if monthly_wage else subsistence
            full = base_amount * percent / 100.0
            # Пропорція за фактично відпрацьований час (неповний місяць).
            if self.scheduled_days and worked < self.scheduled_days:
                full = full * worked / self.scheduled_days
            # The part of it this segment pays.
            entries.append((segment, percent, base_month, full * share))
        parts = self._rounded_parts(
            [entry[3] for entry in entries], lambda value: round(value, 2))
        for (segment, percent, base_month, _exact), amount in zip(entries, parts):
            if amount <= 0:
                continue
            self.env['hr.payslip.accrual'].create({
                'payslip_id': self.id,
                'accrual_type_id': acc_type.id,
                'quantity': 1,
                'rate': percent,
                'amount': amount,
                'is_auto_generated': True,
                'notes': self._segment_note(
                    _('Індексація %.1f%% (баз. міс. %s)') % (
                        percent, base_month.strftime('%m.%Y')),
                    segment, several, versions),
            })

    def _check_tariff_rate(self, version, tariff, on_date):
        """Refuse to pay a day whose rate nobody has entered.

        Without this the statutory floor would quietly stand in for it.
        """
        self.ensure_one()
        if not tariff.hourly_rate:
            raise UserError(_(
                'Tariff grade %(grade)s of %(employee)s has no hourly rate in '
                'force on %(date)s. Enter it in Tariff Grades.',
                grade=version.tariff_grade_id.display_name,
                employee=self.employee_id.name, date=on_date))

    def _tariff_grade(self, version):
        """The version's tariff grade in force at the period end."""
        self.ensure_one()
        tariff = version.tariff_grade_id._l10n_ua_grade_on(self.date_to)
        self._check_tariff_rate(version, tariff, self.date_to)
        return tariff

    def _base_hourly_rate(self, version, params, segment=None):
        """Base hourly rate for surcharges.

        On a tariff grade, the hourly rate of the grade in force; otherwise
        the full-time salary over the norm of the month. Both are full-time
        figures, so the work rate does not enter: an hour of a part-timer
        costs what an hour of the position costs. Never below the statutory
        minimum hourly wage. With a segment, the grade and the salary are the
        ones of its days.
        """
        self.ensure_one()
        min_hourly = params.min_hourly_wage or 0.0
        if getattr(version, 'tariff_grade_id', False):
            if segment:
                self._check_tariff_rate(
                    version, segment['grade'], segment['date_from'])
                rate = segment['grade'].hourly_rate
            else:
                rate = self._tariff_grade(version).hourly_rate
        elif self.scheduled_hours > 0:
            wage = segment['wage'] if segment else self._get_effective_wage(version)
            rate = wage / self.scheduled_hours
        else:
            rate = 0.0
        return max(rate, min_hourly)

    def _generate_time_surcharges(self, segments, params, several=False,
                                  versions=False):
        """Створити авто-доплати за нічні/понаднормові/святкові години.

        Доплати рахуються ЗВЕРХУ базового окладу (модель «доплата»):
        - нічні — % годинної ставки (ст. 108 КЗпП, типово 20%);
        - понаднормові — надлишок до подвійного розміру (ст. 106);
        - святкові — надлишок до подвійного розміру (ст. 107).

        A deviation hour carries a date as a worked hour does, so each is
        paid at the rate of its own day.
        """
        self.ensure_one()
        Accrual = self.env['hr.payslip.accrual']
        AccrualType = self.env['hr.accrual.type']
        night_rate = params.night_surcharge_rate or 0.0
        ot_mult = params.overtime_multiplier or 0.0
        hol_mult = params.holiday_multiplier or 0.0

        for segment in self._surcharge_segments(segments, params):
            hourly = segment['rate']
            if hourly <= 0:
                continue
            surcharges = [
                ('NIGHT', segment['night'], hourly * night_rate / 100.0,
                 _('Доплата за нічні (%.0f%%)') % night_rate),
                ('OVERTIME', segment['overtime'], hourly * max(ot_mult - 1.0, 0.0),
                 _('Понаднормові (×%.2g)') % ot_mult),
                ('HOLIDAY', segment['holiday'], hourly * max(hol_mult - 1.0, 0.0),
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
                    'notes': self._segment_note(
                        note, segment, several, versions),
                })

    def _surcharge_segments(self, segments, params):
        """The segments whose rates the deviations are paid at.

        Piece work is paid by average earnings, which the automatic
        calculation does not do, so its segments are left out.

        A deviation whose days do not add up to the figure on the payslip was
        entered by hand: it has no date to be placed on, so it is paid whole
        at the rate of the last segment — what happened before there were
        segments at all. Nothing is averaged.
        """
        self.ensure_one()
        paid = []
        for segment in segments:
            version = segment['version']
            if getattr(version, 'salary_form', 'time') == 'piece':
                continue
            paid.append(dict(
                segment, rate=self._base_hourly_rate(version, params, segment)))
        if not paid:
            return []
        for key, total in (('night', self.night_hours),
                           ('overtime', self.overtime_hours),
                           ('holiday', self.holiday_hours)):
            if float_compare(sum(segment[key] for segment in paid),
                             total, precision_digits=2) != 0:
                for segment in paid:
                    segment[key] = 0.0
                paid[-1][key] = total
        return paid

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
        params = self.env['hr.psp.parameters'].get_parameters(
            self.date_to, self.company_id.id)
        self._check_psp_parameters_known(params)
        min_wage = params.min_wage

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
        for payslip in self:
            payslip._check_psp_parameters_known(
                self.env['hr.psp.parameters'].get_parameters(
                    payslip.date_to, payslip.company_id.id))
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
