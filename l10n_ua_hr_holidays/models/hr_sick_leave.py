from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrSickLeave(models.Model):
    _name = 'hr.sick.leave'
    _description = 'Sick Leave'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'

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
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    
    sick_leave_number = fields.Char(
        string='Sick Leave Number',
        tracking=True
    )
    is_electronic = fields.Boolean(
        string='Electronic (e-TVN)',
        default=True
    )
    e_sick_leave_id = fields.Char(
        string='e-TVN ID',
        help='Electronic sick leave ID from PFU system'
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
    calendar_days = fields.Integer(
        string='Calendar Days',
        compute='_compute_calendar_days',
        store=True
    )
    
    sick_leave_type = fields.Selection([
        ('illness', 'Illness'),
        ('injury', 'Injury'),
        ('child_care', 'Child Care'),
        ('pregnancy', 'Pregnancy and Childbirth'),
        ('quarantine', 'Quarantine'),
        ('prosthetics', 'Prosthetics'),
        ('sanatorium', 'Sanatorium Treatment'),
    ], string='Type', required=True, default='illness', tracking=True)
    
    diagnosis_code = fields.Char(string='Diagnosis Code (ICD-10)')
    
    insurance_experience_years = fields.Float(
        string='Insurance Experience (years)',
        help='Insurance experience for payment calculation'
    )
    payment_percent = fields.Float(
        string='Payment Percent',
        compute='_compute_payment_percent',
        store=True,
        help='50%, 60%, 70% or 100% based on experience'
    )
    
    average_daily_salary = fields.Float(
        string='Average Daily Salary',
        digits=(16, 2)
    )
    
    employer_days = fields.Integer(
        string='Employer Days',
        compute='_compute_employer_days',
        store=True,
        help='First 5 days paid by employer (0 for pregnancy)'
    )
    employer_amount = fields.Float(
        string='Employer Amount',
        compute='_compute_amounts',
        store=True,
        digits=(16, 2)
    )
    
    fss_days = fields.Integer(
        string='FSS Days',
        compute='_compute_fss_days',
        store=True
    )
    fss_amount = fields.Float(
        string='FSS Amount',
        compute='_compute_amounts',
        store=True,
        digits=(16, 2)
    )
    
    total_amount = fields.Float(
        string='Total Amount',
        compute='_compute_amounts',
        store=True,
        digits=(16, 2)
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    
    leave_id = fields.Many2one(
        'hr.leave',
        string='Related Leave',
        copy=False,
        index=True,
    )
    order_id = fields.Many2one(
        'hr.order',
        string='Related Order',
        ondelete='set null',
        copy=False,
        index=True,
    )
    can_create_leave = fields.Boolean(
        string='Can Create Time Off',
        compute='_compute_can_create_documents',
        help='Technical: true when the "New Time Off" button should be shown — '
             'a sick leave with its dates filled in and no time off linked yet.'
    )
    can_create_order = fields.Boolean(
        string='Can Create Order',
        compute='_compute_can_create_documents',
        help='Technical: true when the "New Order" button should be shown — '
             'a sick leave with an employee and no order linked yet.'
    )

    notes = fields.Text(string='Notes')

    @api.depends('leave_id', 'order_id', 'employee_id', 'date_from', 'date_to')
    def _compute_can_create_documents(self):
        for rec in self:
            rec.can_create_leave = bool(
                not rec.leave_id and rec.employee_id
                and rec.date_from and rec.date_to)
            rec.can_create_order = bool(not rec.order_id and rec.employee_id)

    @api.depends('date_from', 'date_to')
    def _compute_calendar_days(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.calendar_days = (rec.date_to - rec.date_from).days + 1
            else:
                rec.calendar_days = 0

    @api.depends('insurance_experience_years', 'sick_leave_type')
    def _compute_payment_percent(self):
        for rec in self:
            if rec.sick_leave_type == 'pregnancy':
                rec.payment_percent = 100.0
            elif rec.insurance_experience_years < 3:
                rec.payment_percent = 50.0
            elif rec.insurance_experience_years < 5:
                rec.payment_percent = 60.0
            elif rec.insurance_experience_years < 8:
                rec.payment_percent = 70.0
            else:
                rec.payment_percent = 100.0

    @api.depends('sick_leave_type', 'calendar_days')
    def _compute_employer_days(self):
        for rec in self:
            if rec.sick_leave_type == 'pregnancy':
                rec.employer_days = 0
            else:
                rec.employer_days = min(5, rec.calendar_days)

    @api.depends('calendar_days', 'employer_days')
    def _compute_fss_days(self):
        for rec in self:
            rec.fss_days = max(0, rec.calendar_days - rec.employer_days)

    @api.depends('calendar_days', 'employer_days', 'fss_days', 
                 'average_daily_salary', 'payment_percent', 'sick_leave_type')
    def _compute_amounts(self):
        for rec in self:
            daily_rate = (rec.average_daily_salary or 0) * (rec.payment_percent or 0) / 100
            
            if rec.sick_leave_type == 'pregnancy':
                rec.employer_amount = 0.0
                rec.fss_amount = daily_rate * rec.calendar_days
            else:
                actual_employer_days = min(rec.employer_days, rec.calendar_days)
                rec.employer_amount = daily_rate * actual_employer_days
                rec.fss_amount = daily_rate * rec.fss_days
            
            rec.total_amount = rec.employer_amount + rec.fss_amount

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError('Start date must be before end date.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.sick.leave') or 'New'
        return super().create(vals_list)

    def action_calculate(self):
        """Calculate sick leave payment"""
        for rec in self:
            if not rec.employee_id:
                continue
            
            # Get insurance experience
            employee = rec.employee_id
            rec.insurance_experience_years = employee.insurance_experience or 0
            
            # Calculate average daily salary
            rec.average_daily_salary = rec._calculate_average_salary()
        return True

    def _calculate_average_salary(self):
        """Calculate average daily salary for sick leave.

        Based on earnings in billing period (12 months before sick leave).
        According to the Law of Ukraine on Compulsory Social Insurance.
        """
        self.ensure_one()

        # Billing period: 12 calendar months before sick leave
        from dateutil.relativedelta import relativedelta

        date_to = self.date_from.replace(day=1) - relativedelta(days=1)
        date_from = (date_to - relativedelta(months=11)).replace(day=1)

        # Розрахунковий листок дає `l10n_ua_hr_salary`, якого цей модуль не
        # вимагає: відпустки й лікарняні ведуть і без нарахування зарплати.
        # Тому перевіряємо модель, а не поля на ній — усередині гілки склад
        # `hr.payslip` уже відомий і гадати про нього не треба.
        payslips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', '=', 'done'),
        ]) if 'hr.payslip' in self.env else None

        if not payslips:
            # Fallback to contract wage (version in Odoo 19)
            version = self.employee_id.current_version_id
            if version and version.wage:
                # Average days in month for fallback calculation.
                # Оклад може бути у валюті — курс на кінець розрахункового
                # періоду, тобто перед настанням страхового випадку.
                wage = version._l10n_ua_wage_in_company_currency(date_to)
                return round(wage / 30.44, 2)
            return 0.0

        # Calculate total earnings from payslip lines
        total_earnings = 0.0
        total_calendar_days = 0

        for payslip in payslips:
            # Calculate calendar days in payslip period
            payslip_days = (payslip.date_to - payslip.date_from).days + 1
            total_calendar_days += payslip_days

            # УВАГА: береться весь нарахований дохід. `hr.accrual.type` має
            # прапорець `is_basic_salary` («Include in average salary
            # calculation»), і саме за ним мав би йти відбір — але тут він
            # ніколи не застосовувався, тож зміна одразу зрушила б суми
            # лікарняних. Питання відбору за П. 100 / № 1266 заведено окремо.
            total_earnings += payslip.gross_salary or 0

        if total_calendar_days > 0:
            return round(total_earnings / total_calendar_days, 2)
        return 0.0

    def _sick_leave_type(self):
        """The sick leave type, or an empty recordset.

        Odoo 20 scopes hr.work.entry.type by country, so there is one UA
        sick leave type for every company of the database.
        """
        self.ensure_one()
        return self.env['hr.work.entry.type'].search([
            ('ua_leave_category', '=', 'sick'),
        ], limit=1)

    def action_create_leave(self):
        """"New Time Off" button. Opens a leave form pre-filled from this sick
        leave so the user reviews and saves it explicitly.

        Confirming a sick leave used to create the absence in the background
        and approve it on the spot, which put an employee on approved leave
        with no author and no trail, and skipped the approval gate of
        hr_holidays entirely. Documents are created by whoever has the right
        to create them, one button at a time — the same flow vacation orders
        use.
        """
        self.ensure_one()
        if self.leave_id:
            raise UserError(_('This sick leave already has a linked time off.'))
        leave_type = self._sick_leave_type()
        if not leave_type:
            raise UserError(_(
                'No sick leave type is configured. Create a time off type '
                'with the Ukrainian category "Sick Leave" first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Time Off'),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_work_entry_type_id': leave_type.id,
                'default_request_date_from': self.date_from,
                'default_request_date_to': self.date_to,
                'default_name': _('Sick Leave %s', self.name),
                'default_sick_leave_id': self.id,
            },
        }

    def action_create_order(self):
        """"New Order" button. Opens a sick-leave order pre-filled from this
        record; nothing is created until the user saves it."""
        self.ensure_one()
        if self.order_id:
            raise UserError(_('This sick leave already has a linked order.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Order'),
            'res_model': 'hr.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_order_type': 'sick_leave',
                'default_employee_id': self.employee_id.id,
                'default_department_id': self.employee_id.department_id.id,
                'default_job_id': self.employee_id.job_id.id,
                'default_sick_leave_id': self.id,
            },
        }

    def action_view_leave(self):
        """Smart button: open the time off recorded for this sick leave."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'res_id': self.leave_id.id,
        }

    def action_view_order(self):
        """Smart button: open the order issued for this sick leave."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.order',
            'view_mode': 'form',
            'res_id': self.order_id.id,
        }

    def action_confirm(self):
        """Confirm the sick leave. The absence and the order are separate
        documents, created through their own buttons."""
        self.write({'state': 'confirmed'})

    def action_pay(self):
        self.write({'state': 'paid'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_draft(self):
        self.write({'state': 'draft'})
