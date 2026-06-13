from odoo import models, fields


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    ua_leave_category = fields.Selection([
        ('annual_basic', 'Annual Basic Leave'),
        ('annual_additional', 'Annual Additional Leave'),
        ('annual_hazardous', 'Additional Leave for Hazardous Conditions'),
        ('annual_special', 'Additional Leave for Special Work Nature'),
        ('annual_irregular', 'Additional Leave for Irregular Hours'),
        ('educational', 'Educational Leave'),
        ('creative', 'Creative Leave'),
        ('social', 'Social Leave'),
        ('social_children', 'Additional Leave for Workers with Children'),
        ('chornobyl', 'Additional Leave for Chornobyl Victims'),
        ('veteran', 'Additional Leave for War Veterans'),
        ('unpaid', 'Unpaid Leave'),
        ('maternity', 'Maternity Leave'),
        ('childcare', 'Childcare Leave'),
        ('sick', 'Sick Leave'),
        ('other', 'Other'),
    ], string='UA Leave Category')
    
    annual_days = fields.Integer(
        string='Days per Year',
        default=24,
        help='Number of vacation days per year (24 is standard)'
    )
    is_calendar_days = fields.Boolean(
        string='Calendar Days',
        default=True,
        help='If checked, vacation is counted in calendar days'
    )
    period_type = fields.Selection([
        ('calendar', 'Calendar Year'),
        ('work', 'Work Year'),
    ], string='Accounting Period', default='calendar', required=True,
        help='Calendar Year: Jan 1 – Dec 31. '
             'Work Year: 12-month period from the employee hire_date '
             '(per Ukrainian Vacation Law art. 6, 7, 8, 10).'
    )
    is_transferable = fields.Boolean(
        string='Transferable',
        default=True,
        help='Can unused days be transferred to next year'
    )
    max_transfer_days = fields.Integer(
        string='Max Transfer Days',
        help='Maximum days that can be transferred'
    )
    requires_experience = fields.Boolean(
        string='Requires Work Experience',
        help='Requires 6 months of work experience'
    )
    min_experience_months = fields.Integer(
        string='Min Experience (months)',
        default=6
    )
    is_paid = fields.Boolean(
        string='Paid Leave',
        default=True
    )
    payment_source = fields.Selection([
        ('employer', 'Employer'),
        ('fss', 'Social Insurance Fund'),
        ('mixed', 'Mixed'),
    ], string='Payment Source', default='employer')
    
    min_continuous_days = fields.Integer(
        string='Min Continuous Days',
        default=14,
        help='Minimum continuous vacation days (14 for annual)'
    )
    max_carryover_years = fields.Integer(
        string='Max Carryover Years',
        default=2,
        help='Maximum years unused vacation can be carried over (Ukrainian law: 2 years)'
    )
    max_additional_days = fields.Integer(
        string='Max Additional Days',
        help='Maximum additional days for this leave type (e.g., 35 for hazardous, 7 for irregular)'
    )
    create_order = fields.Boolean(
        string='Create Order',
        default=False,
        help='Automatically create a vacation order (form П-3) when a leave of this type is created',
    )
