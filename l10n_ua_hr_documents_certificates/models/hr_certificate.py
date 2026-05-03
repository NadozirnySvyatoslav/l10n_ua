import logging
from lxml import etree
from odoo import models, fields, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class HrCertificate(models.Model):
    _name = 'hr.certificate'
    _description = 'HR Certificate'
    _order = 'issue_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'

    name = fields.Char(
        string='Number',
        readonly=True,
        copy=False,
        default='New',
        tracking=True
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    certificate_type_id = fields.Many2one(
        'hr.certificate.type',
        string='Certificate Type',
        required=True,
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
        default=lambda self: self.env.company,
        required=True
    )

    # Dates
    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        tracking=True
    )
    issue_date = fields.Date(
        string='Issue Date',
        tracking=True
    )
    valid_until = fields.Date(
        string='Valid Until',
        compute='_compute_valid_until',
        store=True
    )

    # Destination
    destination = fields.Char(
        string='Destination',
        default='за місцем вимоги',
        help='Where the certificate will be presented'
    )

    # Settings from type (for visibility in form)
    requires_salary_info = fields.Boolean(
        related='certificate_type_id.requires_salary_info'
    )
    requires_period = fields.Boolean(
        related='certificate_type_id.requires_period'
    )
    requires_destination = fields.Boolean(
        related='certificate_type_id.requires_destination'
    )

    # Period (for salary/income certificates)
    period_from = fields.Date(
        string='Period From'
    )
    period_to = fields.Date(
        string='Period To'
    )

    # Salary information (computed or manual)
    salary_amount = fields.Monetary(
        string='Current Salary',
        compute='_compute_salary_info',
        store=True,
        readonly=False,
        currency_field='currency_id'
    )
    total_income = fields.Monetary(
        string='Total Income (Period)',
        currency_field='currency_id',
        help='Total income for the specified period'
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id
    )

    # Generated content
    body = fields.Html(
        string='Certificate Body',
        sanitize=False,
        help='Certificate content. Loaded from template, can be edited.'
    )

    # Workflow
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    # Additional info
    notes = fields.Text(string='Internal Notes')
    issued_by = fields.Many2one(
        'res.users',
        string='Issued By',
        tracking=True
    )
    copies_count = fields.Integer(
        string='Number of Copies',
        default=1
    )

    @api.depends('employee_id', 'certificate_type_id', 'name')
    def _compute_display_name(self):
        for record in self:
            if record.employee_id and record.certificate_type_id:
                record.display_name = f"{record.name} - {record.employee_id.name} ({record.certificate_type_id.name})"
            else:
                record.display_name = record.name or 'New'

    @api.depends('issue_date', 'certificate_type_id.validity_days')
    def _compute_valid_until(self):
        for record in self:
            if record.issue_date and record.certificate_type_id.validity_days:
                record.valid_until = record.issue_date + relativedelta(days=record.certificate_type_id.validity_days)
            else:
                record.valid_until = False

    @api.depends('employee_id')
    def _compute_salary_info(self):
        for record in self:
            if record.employee_id:
                # Try to get salary from Ukrainian contract
                if hasattr(record.employee_id, 'contract_ua_id') and record.employee_id.contract_ua_id:
                    record.salary_amount = record.employee_id.contract_ua_id.wage
                # Fallback to hr.version wage
                elif record.employee_id.version_id:
                    record.salary_amount = record.employee_id.version_id.wage
                else:
                    record.salary_amount = 0
            else:
                record.salary_amount = 0

    @api.onchange('certificate_type_id')
    def _onchange_certificate_type_id(self):
        """Load template body when certificate type is selected"""
        if self.certificate_type_id and self.certificate_type_id.template_body:
            self.body = self.certificate_type_id.template_body

    @api.onchange('certificate_type_id', 'employee_id', 'destination', 'period_from',
                  'period_to', 'salary_amount', 'total_income')
    def _onchange_render_body(self):
        """Re-render body when relevant fields change"""
        if self.certificate_type_id and self.certificate_type_id.template_body and self.employee_id:
            self.body = self._render_template(self.certificate_type_id.template_body)

    def action_load_template(self):
        """Reload template from certificate type"""
        for record in self:
            if record.certificate_type_id and record.certificate_type_id.template_body:
                record.body = record._render_template(record.certificate_type_id.template_body)

    def _render_template(self, template):
        """Render template using QWeb engine"""
        self.ensure_one()

        context = self._get_render_context()

        try:
            qweb_template = f'<t>{template}</t>'
            # Parse as XML element
            template_element = etree.fromstring(qweb_template.encode('utf-8'))
            # Render using QWeb
            result = self.env['ir.qweb']._render(template_element, context)
            return str(result)
        except Exception as e:
            _logger.error(f"QWeb rendering failed: {e}")
            # Fallback: return template as-is
            return template

    def _get_render_context(self):
        """Prepare context for QWeb template rendering"""
        self.ensure_one()

        employee = self.employee_id
        company = self.company_id

        # Get company director
        director = False
        director_position = 'Директор'
        if hasattr(company, 'director_id') and company.director_id:
            director = company.director_id
            director_position = director.job_id.name if director.job_id else 'Директор'

        # Chief accountant from company settings
        accountant = False
        if hasattr(company, 'accountant_id') and company.accountant_id:
            accountant = company.accountant_id

        # Get hire date from contract (if hr_contract module is installed)
        hire_date = False
        contract = False
        if employee and 'hr.contract' in self.env:
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'open')
            ], limit=1)
            if contract:
                hire_date = contract.date_start

        # Calculate work experience
        work_experience = self._calculate_work_experience(hire_date)

        return {
            'o': self,
            'certificate': self,
            'employee': employee,
            'company': company,
            'director': director,
            'director_position': director_position,
            'accountant': accountant,
            'contract': contract,
            'hire_date': hire_date,
            'work_experience': work_experience,
            'destination': self.destination or 'за місцем вимоги',
            'format_date': self._format_date,
            'format_money': self._format_money,
        }

    def _calculate_work_experience(self, hire_date):
        """Calculate work experience string"""
        if not hire_date:
            return ''
        delta = relativedelta(fields.Date.today(), hire_date)
        parts = []
        if delta.years:
            parts.append(f"{delta.years} р.")
        if delta.months:
            parts.append(f"{delta.months} міс.")
        return ' '.join(parts) if parts else 'менше місяця'

    def _format_date(self, date_val, fmt='%d.%m.%Y'):
        """Format date helper for templates"""
        if date_val:
            return date_val.strftime(fmt)
        return ''

    def _format_money(self, amount):
        """Format monetary amount"""
        if amount:
            return f"{amount:,.2f}".replace(',', ' ')
        return ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                # Get sequence from certificate type
                if vals.get('certificate_type_id'):
                    cert_type = self.env['hr.certificate.type'].browse(vals['certificate_type_id'])
                    if cert_type.sequence_id:
                        vals['name'] = cert_type.sequence_id.next_by_id()
                    else:
                        vals['name'] = self.env['ir.sequence'].next_by_code(
                            f'hr.certificate.{cert_type.code}'
                        ) or self.env['ir.sequence'].next_by_code('hr.certificate') or 'New'
                else:
                    vals['name'] = self.env['ir.sequence'].next_by_code('hr.certificate') or 'New'
        return super().create(vals_list)

    def action_approve(self):
        """Approve the certificate request"""
        for record in self:
            if record.state != 'draft':
                raise UserError('Only draft certificates can be approved.')
            record.state = 'approved'

    def action_issue(self):
        """Issue the certificate"""
        for record in self:
            if record.state != 'approved':
                raise UserError('Only approved certificates can be issued.')
            record.write({
                'state': 'issued',
                'issue_date': fields.Date.today(),
                'issued_by': self.env.user.id,
            })
            # Re-render body with final data
            if record.certificate_type_id.template_body:
                record.body = record._render_template(record.certificate_type_id.template_body)

    def action_cancel(self):
        """Cancel the certificate"""
        for record in self:
            if record.state == 'issued':
                raise UserError('Cannot cancel an issued certificate. Create a new one instead.')
            record.state = 'cancelled'

    def action_draft(self):
        """Reset to draft"""
        for record in self:
            if record.state == 'issued':
                raise UserError('Cannot reset an issued certificate to draft.')
            record.state = 'draft'

    def action_print(self):
        """Print the certificate"""
        self.ensure_one()
        # Use custom report if defined, otherwise use default
        if self.certificate_type_id.report_id:
            return self.certificate_type_id.report_id.report_action(self)
        return self.env.ref('l10n_ua_hr_documents_certificates.action_report_hr_certificate').report_action(self)
