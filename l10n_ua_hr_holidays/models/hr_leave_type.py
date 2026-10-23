from odoo import models, fields, api, _

# Unpaid leave of any kind: no pay is kept for these days.
UNPAID_LEAVE_CATEGORIES = ('unpaid', 'unpaid_abroad', 'unpaid_childcare')

# Annual leave, basic and additional.
ANNUAL_LEAVE_CATEGORIES = (
    'annual_basic', 'annual_additional', 'annual_hazardous',
    'annual_special', 'annual_irregular',
)

# Leave whose unused days are paid out on dismissal: every annual leave and
# the additional leave of workers with children.
COMPENSATED_LEAVE_CATEGORIES = ANNUAL_LEAVE_CATEGORIES + ('social_children',)


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
        ('unpaid_abroad', 'Unpaid Leave (Abroad or Internally Displaced)'),
        ('unpaid_childcare', 'Unpaid Leave (Childcare)'),
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
    ua_is_default = fields.Boolean(
        string='Show by Default',
        copy=False,
        help='Preselect this leave type by default. Only one leave type per '
             'company may be the default at a time.',
    )

    ua_auto_calc_balance = fields.Boolean(
        string='Auto-calculate Balance',
        default=False,
        help='When enabled, the "Recalculate" action in Vacation Balances '
             'generates and maintains the accounting periods for this leave '
             'type. Off by default — only types with this ticked are '
             'recalculated.',
    )

    def _default_conflicts(self):
        """Other leave types of the same company already flagged as default."""
        self.ensure_one()
        return self.search([
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('ua_is_default', '=', True),
        ])

    def write(self, vals):
        """Handle ua_is_default checkbox: when set to True, clear other
        defaults in the same company."""
        res = super().write(vals)
        if 'ua_is_default' in vals and vals['ua_is_default']:
            for record in self:
                conflicts = record._default_conflicts()
                if conflicts:
                    conflicts.write({'ua_is_default': False})
        return res
