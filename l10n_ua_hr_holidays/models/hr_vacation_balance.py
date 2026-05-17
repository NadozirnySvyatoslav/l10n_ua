from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta


class HrVacationBalance(models.Model):
    _name = 'hr.vacation.balance'
    _description = 'Vacation Balance'
    _order = 'year desc, employee_id'
    _rec_name = 'display_name'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        check_company=True
    )
    leave_type_id = fields.Many2one(
        'hr.leave.type',
        string='Leave Type',
        required=True,
        domain="[('ua_leave_category', 'in', ['annual_basic', 'annual_additional'])]"
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    entitled_days = fields.Float(
        string='Entitled Days',
        compute='_compute_entitled_days',
        store=True,
        readonly=False,
        precompute=True,
        help='Days entitled for the year. Defaults to leave type annual_days; '
             'can be overridden manually (e.g. proportional for mid-year hires).'
    )
    carried_over = fields.Float(
        string='Carried Over',
        help='Days carried from previous year'
    )
    total_available = fields.Float(
        string='Total Available',
        compute='_compute_totals',
        store=True
    )
    
    used_days = fields.Float(
        string='Used Days',
        compute='_compute_used_days',
        store=True
    )
    planned_days = fields.Float(
        string='Planned Days',
        compute='_compute_used_days',
        store=True
    )
    remaining_days = fields.Float(
        string='Remaining Days',
        compute='_compute_totals',
        store=True
    )
    
    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    @api.depends('leave_type_id')
    def _compute_entitled_days(self):
        for rec in self:
            if rec.leave_type_id and not rec.entitled_days:
                rec.entitled_days = rec.leave_type_id.annual_days or 0

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.employee_id = False
        self.leave_type_id = False

    @api.depends('entitled_days', 'carried_over', 'used_days')
    def _compute_totals(self):
        for rec in self:
            rec.total_available = (rec.entitled_days or 0) + (rec.carried_over or 0)
            rec.remaining_days = rec.total_available - (rec.used_days or 0)

    @api.depends('employee_id', 'leave_type_id', 'year')
    def _compute_used_days(self):
        HrLeave = self.env['hr.leave']
        for rec in self:
            if not rec.employee_id or not rec.leave_type_id or not rec.year:
                rec.used_days = 0
                rec.planned_days = 0
                continue

            year_start = fields.Date.from_string(f'{rec.year}-01-01')
            year_end = fields.Date.from_string(f'{rec.year}-12-31')

            base_domain = [
                ('employee_id', '=', rec.employee_id.id),
                ('holiday_status_id', '=', rec.leave_type_id.id),
                '|',
                    ('vacation_year', '=', rec.year),
                    '&', '&',
                        ('vacation_year', 'in', [False, 0]),
                        ('request_date_from', '<=', year_end),
                        ('request_date_to', '>=', year_start),
            ]

            used_leaves = HrLeave.search(base_domain + [('state', '=', 'validate')])
            rec.used_days = sum(used_leaves.mapped('calendar_days'))

            planned_leaves = HrLeave.search(base_domain + [
                ('state', 'in', ('draft', 'confirm', 'validate1')),
            ])
            rec.planned_days = sum(planned_leaves.mapped('calendar_days'))

    @api.depends('employee_id', 'year')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.employee_id.name} - {rec.year}'

    @api.model
    def generate_balances(self, year=None):
        """Generate vacation balances for all employees"""
        if year is None:
            year = fields.Date.today().year
        
        domain = []
        if 'contract_id' in self.env['hr.employee']._fields:
            domain.append(('contract_id.state', '=', 'open'))
        
        employees = self.env['hr.employee'].search(domain)
        
        annual_leave_type = self.env['hr.leave.type'].search([
            ('ua_leave_category', '=', 'annual_basic'),
        ], limit=1)
        
        if not annual_leave_type:
            return
        
        for employee in employees:
            existing = self.search([
                ('employee_id', '=', employee.id),
                ('leave_type_id', '=', annual_leave_type.id),
                ('year', '=', year),
            ])
            
            if existing:
                continue
            
            # Get previous year balance
            prev_balance = self.search([
                ('employee_id', '=', employee.id),
                ('leave_type_id', '=', annual_leave_type.id),
                ('year', '=', year - 1),
            ], limit=1)
            
            carried = prev_balance.remaining_days if prev_balance else 0
            
            self.create({
                'employee_id': employee.id,
                'leave_type_id': annual_leave_type.id,
                'year': year,
                'entitled_days': annual_leave_type.annual_days,
                'carried_over': carried,
            })

    def _recompute_related_leaves(self):
        """
        Helper method to force recomputation of remaining days for all leaves 
        associated with this balance record.
        """
        for balance in self:
            leaves = self.env['hr.leave'].search([
                ('employee_id', '=', balance.employee_id.id),
                ('holiday_status_id', '=', balance.leave_type_id.id),
                '|', ('vacation_year', '=', balance.year),
                     '&', ('request_date_from', '>=', f'{balance.year}-01-01'),
                          ('request_date_from', '<=', f'{balance.year}-12-31')
            ])
            if leaves:
                # Sort chronologically to ensure cascading subtraction is correct
                sorted_leaves = leaves.sorted(key=lambda l: l.request_date_from or fields.Date.today())
                sorted_leaves._compute_remaining_before()
                sorted_leaves._compute_remaining_after()

    @api.model_create_multi
    def create(self, vals_list):
        balances = super().create(vals_list)
        # Trigger recomputation for existing leaves when a balance is manually created
        balances._recompute_related_leaves()
        return balances

    def write(self, vals):
        res = super().write(vals)
        # Trigger recomputation only when base days or year are modified
        if any(field in vals for field in ['entitled_days', 'carried_over', 'year', 'employee_id', 'leave_type_id']):
            self._recompute_related_leaves()
        return res

    _unique_employee_id_leave_type_id_year = models.Constraint(
        'unique(employee_id, leave_type_id, year)',
        'Balance for this employee, leave type and year already exists!',
    )

    @api.constrains('carried_over', 'year', 'employee_id', 'leave_type_id')
    def _check_carryover_limit(self):
        """Check that vacation is not carried over for more than max_carryover_years.
        
        Ukrainian law requires that vacation must be used within 2 years.
        """
        for rec in self:
            if not rec.carried_over or rec.carried_over <= 0:
                continue
            
            max_years = rec.leave_type_id.max_carryover_years or 2
            
            oldest_allowed_year = rec.year - max_years
            old_balances = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('year', '<=', oldest_allowed_year),
                ('remaining_days', '>', 0),
            ])
            
            if old_balances:
                raise ValidationError(_(
                    'Employee %(employee)s has unused vacation days from %(year)s or earlier. '
                    'According to Ukrainian law, vacation must be used within %(max_years)s years.',
                    employee=rec.employee_id.name,
                    year=oldest_allowed_year,
                    max_years=max_years,
                ))

    def calculate_compensation(self, termination_date=None, is_termination=True):
        """Calculate compensation for unused vacation.

        Args:
            termination_date: Date of termination/calculation (defaults to today)
            is_termination: If True, compensate all unused days (on termination).
                           If False, only compensate days over 24 (without termination).

        Returns:
            float: Compensation amount for unused vacation days
            
        Per Ukrainian law:
        - On termination: all unused days are compensated
        - Without termination: only days over 24 can be compensated,
          and employee must have used at least 24 days in current year
        """
        self.ensure_one()

        if not self.employee_id or not self.remaining_days:
            return 0.0

        if termination_date is None:
            termination_date = fields.Date.today()

        compensable_days = self.remaining_days
        
        if not is_termination:
            min_annual_days = self.leave_type_id.annual_days or 24
            if self.used_days < min_annual_days:
                return 0.0
            compensable_days = max(0, self.remaining_days - min_annual_days)
            if compensable_days <= 0:
                return 0.0

        # Get average daily salary using hr.leave calculation
        leave = self.env['hr.leave'].new({
            'employee_id': self.employee_id.id,
            'date_from': termination_date,
        })
        avg_salary = leave._calculate_average_salary()

        if avg_salary <= 0:
            return 0.0

        compensation = compensable_days * avg_salary
        return round(compensation, 2)

    def action_calculate_compensation(self):
        """Action to calculate and display compensation amount."""
        self.ensure_one()
        compensation = self.calculate_compensation()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vacation Compensation'),
                'message': _('Compensation for %(days)s unused days: %(amount).2f UAH', days=self.remaining_days, amount=compensation),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_recalculate(self):
        for rec in self:
            if rec.leave_type_id and not rec.entitled_days:
                rec.entitled_days = rec.leave_type_id.annual_days or 0
        self.invalidate_recordset([
            'used_days', 'planned_days', 'total_available', 'remaining_days',
        ])
        self._compute_used_days()
        self._compute_totals()
        return True

    def action_recalculate_all(self):
        """
        Recalculate or generate vacation balances for the current year
        for all active employees.
        """
        current_year = fields.Date.today().year
        self.generate_balances(year=current_year)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recalculation Complete'),
                'message': _('Vacation balances for %s have been updated for all active employees.', current_year),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }
