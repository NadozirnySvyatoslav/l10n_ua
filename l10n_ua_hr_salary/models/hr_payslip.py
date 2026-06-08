from odoo import models, fields, api
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import calendar


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

    @api.depends('employee_id')
    def _compute_employee_benefits(self):
        """Compute employee benefit flags for special tax regimes"""
        for payslip in self:
            is_disability = False
            is_diia_city = False

            if payslip.employee_id:
                # Check for disability benefits
                if hasattr(payslip.employee_id, 'benefit_ids') and payslip.employee_id.benefit_ids:
                    for benefit in payslip.employee_id.benefit_ids:
                        code_lower = (benefit.code or '').lower()
                        name_lower = (benefit.name or '').lower()
                        if 'disability' in code_lower or 'інвалід' in name_lower:
                            is_disability = True
                            break

                # Check for Diia.City status from contract version
                version = payslip.version_id or payslip.employee_id.current_version_id
                if version and hasattr(version, 'diia_city_employee'):
                    is_diia_city = version.diia_city_employee or False
                if version and hasattr(version, 'contract_type_ua'):
                    if version.contract_type_ua == 'gig':
                        is_diia_city = True

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

            # PDFO base and amount
            pdfo_taxable = sum(
                a.amount for a in payslip.accrual_ids
                if a.is_taxable_pdfo
            )
            payslip.pdfo_base = max(0, pdfo_taxable - payslip.psp_amount)
            payslip.pdfo_amount = round(payslip.pdfo_base * pdfo_rate / 100, 2)

            # Military tax
            military_taxable = sum(
                a.amount for a in payslip.accrual_ids
                if a.is_military_tax
            )
            payslip.military_tax_base = military_taxable
            payslip.military_tax_amount = round(military_taxable * military_rate / 100, 2)

            # ESV (employer contribution)
            params = self.env['hr.psp.parameters'].get_parameters(payslip.date_to)
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
        
        self.scheduled_days = total_scheduled
        self.scheduled_hours = total_scheduled * 8.0
        
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
                # in case if there is multiplier in timesheets 
                if ts_line.scheduled_days:
                    self.scheduled_days = ts_line.scheduled_days
                    self.scheduled_hours = ts_line.scheduled_days * 8.0
                return

        # default if there is no timesheets
        worked = 0
        curr = self.date_from
        while curr <= self.date_to:
            if curr.weekday() < 5:
                worked += 1
            curr += relativedelta(days=1)
        self.worked_days = worked
        self.worked_hours = worked * 8.0


    def _get_effective_wage(self, version):
        """Get effective wage considering staffing table fallback"""
        wage = version.wage or 0.0

        if wage > 0:
            return wage

        # Check company setting for staffing table fallback
        setting = self.company_id.wage_from_staffing if hasattr(self.company_id, 'wage_from_staffing') else 'both'

        if setting in ('fallback', 'both'):
            # Try to get wage from staffing table
            if hasattr(version, 'staffing_line_id') and version.staffing_line_id:
                staffing = version.staffing_line_id
                if staffing.salary:
                    return staffing.salary

        return wage

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

        version = self.version_id

        salary_type = self.env['hr.accrual.type'].search([('code', '=', 'SALARY')], limit=1)
        params = self.env['hr.psp.parameters'].get_parameters(self.date_to)
        
        if salary_type:
            # tariff grade calculations
            if hasattr(version, 'tariff_grade_id') and version.tariff_grade_id:

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
                if effective_wage and self.scheduled_days > 0:
                    # scheduled_days - number of expected working days in the months
                    daily_rate = effective_wage / self.scheduled_days
                    
                    if self.worked_days >= self.scheduled_days:
                        amount = effective_wage # full amount if worked all days 
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

        # Version allowances
        allowance_type = self.env['hr.accrual.type'].search([('code', '=', 'ALLOWANCE')], limit=1)
        if allowance_type and hasattr(version, 'allowance_ids'):
            for allowance in version.allowance_ids.filtered('is_active'):
                self.env['hr.payslip.accrual'].create({
                    'payslip_id': self.id,
                    'accrual_type_id': allowance_type.id,
                    'quantity': 1,
                    'amount': allowance.calculated_amount,
                    'notes': allowance.allowance_type_id.name,
                    'is_auto_generated': True,
                })

    def _generate_deductions(self):
        """Generate deduction lines.

        Only auto-generated deductions are deleted and recreated.
        Manual deductions added by user are preserved.
        """
        self.ensure_one()
        # Delete only auto-generated deductions, preserve manual ones
        self.deduction_ids.filtered('is_auto_generated').unlink()
        
        # Execution documents
        exec_docs = self.env['hr.execution.document'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'active'),
            ('date_from', '<=', self.date_to),
            '|', ('date_to', '>=', self.date_from), ('date_to', '=', False),
        ])
        
        alimony_type = self.env['hr.deduction.type'].search([('code', '=', 'ALIMONY')], limit=1)
        
        for doc in exec_docs:
            if doc.calculation_method == 'percent':
                amount = self.gross_salary * doc.percent_value / 100
            elif doc.calculation_method == 'fixed':
                amount = doc.fixed_amount
            else:
                params = self.env['hr.psp.parameters'].get_parameters(self.date_to)
                min_wage = params.min_wage if params else 8000
                amount = min_wage * doc.percent_value / 100
            
            self.env['hr.payslip.deduction'].create({
                'payslip_id': self.id,
                'deduction_type_id': alimony_type.id if alimony_type else False,
                'base_amount': self.gross_salary,
                'rate': doc.percent_value if doc.calculation_method == 'percent' else 0,
                'amount': round(amount, 2),
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
