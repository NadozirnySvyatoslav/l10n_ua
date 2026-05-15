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
        string='Period From',
        compute='_compute_period_defaults',
        store=True,
        readonly=False,
    )
    period_to = fields.Date(
        string='Period To',
        compute='_compute_period_defaults',
        store=True,
        readonly=False,
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
        compute='_compute_total_income',
        store=True,
        readonly=False,
        help='Total gross income for the specified period (auto-summed from payslips when available)'
    )
    total_pdfo = fields.Monetary(
        string='Total PDFO',
        currency_field='currency_id',
        compute='_compute_total_income',
        store=True,
        readonly=False,
    )
    total_military_tax = fields.Monetary(
        string='Total Military Tax',
        currency_field='currency_id',
        compute='_compute_total_income',
        store=True,
        readonly=False,
    )
    total_esv = fields.Monetary(
        string='Total ESV (Employer)',
        currency_field='currency_id',
        compute='_compute_total_income',
        store=True,
        readonly=False,
    )
    total_net = fields.Monetary(
        string='Total Net',
        currency_field='currency_id',
        compute='_compute_total_income',
        store=True,
        readonly=False,
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

    @api.depends('employee_id', 'employee_id.current_version_id', 'employee_id.current_version_id.wage')
    def _compute_salary_info(self):
        for record in self:
            version = record._get_employee_version()
            record.salary_amount = version.wage if version else 0

    @api.depends('certificate_type_id', 'request_date')
    def _compute_period_defaults(self):
        """Auto-fill period for cert types that need it (default: last 6 calendar months)."""
        for record in self:
            if not record.certificate_type_id or not record.certificate_type_id.requires_period:
                continue
            if record.period_from and record.period_to:
                continue
            anchor = record.request_date or fields.Date.context_today(record)
            first_of_month = anchor.replace(day=1)
            record.period_to = first_of_month - relativedelta(days=1)
            record.period_from = (record.period_to + relativedelta(days=1)) - relativedelta(months=6)

    @api.depends('employee_id', 'period_from', 'period_to')
    def _compute_total_income(self):
        for record in self:
            payslips = record._get_payslips_for_period()
            if payslips:
                record.total_income = sum(p.gross_salary for p in payslips)
                record.total_pdfo = sum(p.pdfo_amount for p in payslips)
                record.total_military_tax = sum(p.military_tax_amount for p in payslips)
                record.total_esv = sum(p.esv_amount for p in payslips)
                record.total_net = sum(p.net_salary for p in payslips)
            else:
                record.total_income = record.total_income or 0
                record.total_pdfo = record.total_pdfo or 0
                record.total_military_tax = record.total_military_tax or 0
                record.total_esv = record.total_esv or 0
                record.total_net = record.total_net or 0

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

    def _get_employee_version(self):
        """Current active hr.version for the employee, or latest if no current."""
        self.ensure_one()
        if not self.employee_id:
            return self.env['hr.version']
        version = self.employee_id.current_version_id
        if version:
            return version
        return self.env['hr.version'].search(
            [('employee_id', '=', self.employee_id.id)],
            order='date_version desc', limit=1,
        )

    def _get_hire_date(self):
        """Initial employment start date — earliest contract_date_start across versions."""
        self.ensure_one()
        if not self.employee_id:
            return False
        version = self.env['hr.version'].search(
            [('employee_id', '=', self.employee_id.id),
             ('contract_date_start', '!=', False)],
            order='contract_date_start asc', limit=1,
        )
        if version:
            return version.contract_date_start
        first_any = self.env['hr.version'].search(
            [('employee_id', '=', self.employee_id.id)],
            order='date_version asc', limit=1,
        )
        return first_any.date_version if first_any else False

    def _get_payslips_for_period(self):
        """Return done/paid payslips overlapping the requested period."""
        self.ensure_one()
        if not self.employee_id or not self.period_from or not self.period_to:
            return self.env['hr.payslip'] if 'hr.payslip' in self.env else []
        if 'hr.payslip' not in self.env:
            return []
        return self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ('done', 'paid')),
            ('date_from', '>=', self.period_from),
            ('date_to', '<=', self.period_to),
        ], order='date_from')

    def _get_monthly_breakdown(self):
        """List of dicts per payslip for table rendering in templates."""
        return [{
            'period': p.date_from.strftime('%m.%Y') if p.date_from else '',
            'date_from': p.date_from,
            'date_to': p.date_to,
            'gross': p.gross_salary,
            'pdfo': p.pdfo_amount,
            'military_tax': p.military_tax_amount,
            'esv': p.esv_amount,
            'net': p.net_salary,
        } for p in self._get_payslips_for_period()]

    def _get_render_context(self):
        """Prepare context for QWeb template rendering."""
        self.ensure_one()

        employee = self.employee_id
        company = self.company_id

        director = company.director_id
        director_position = director.job_id.name if director and director.job_id else 'Директор'
        accountant = company.accountant_id
        hr_manager = company.hr_manager_id

        version = self._get_employee_version()
        hire_date = self._get_hire_date()
        work_experience = self._calculate_work_experience(hire_date)

        contract_type_ua = dict(
            version._fields['contract_type_ua'].selection
        ).get(version.contract_type_ua, '') if version and 'contract_type_ua' in version._fields else ''
        is_fixed_term = bool(version.contract_date_end) if version else False

        return {
            'o': self,
            'certificate': self,
            'employee': employee,
            'company': company,
            'director': director,
            'director_position': director_position,
            'accountant': accountant,
            'hr_manager': hr_manager,
            'version': version,
            'hire_date': hire_date,
            'contract_end_date': version.contract_date_end if version else False,
            'contract_type_ua': contract_type_ua,
            'is_fixed_term': is_fixed_term,
            'hire_order_number': version.hire_order_number if version and 'hire_order_number' in version._fields else '',
            'hire_order_date': version.hire_order_date if version and 'hire_order_date' in version._fields else False,
            'wage': version.wage if version else 0,
            'work_experience': work_experience,
            'monthly_breakdown': self._get_monthly_breakdown(),
            'destination': self.destination or 'за місцем вимоги',
            'format_date': self._format_date,
            'format_money': self._format_money,
            'amount_to_words': self._amount_to_words_ua,
            'rnokpp': employee.rnokpp if employee else '',
            'today': fields.Date.context_today(self),
        }

    def _calculate_work_experience(self, hire_date):
        """Format work experience as 'X р. Y міс. Z дн.'"""
        if not hire_date:
            return ''
        delta = relativedelta(fields.Date.today(), hire_date)
        parts = []
        if delta.years:
            parts.append(f"{delta.years} р.")
        if delta.months:
            parts.append(f"{delta.months} міс.")
        if delta.days:
            parts.append(f"{delta.days} дн.")
        return ' '.join(parts) if parts else 'менше місяця'

    def _format_date(self, date_val, fmt='%d.%m.%Y'):
        if date_val:
            return date_val.strftime(fmt)
        return ''

    def _format_money(self, amount):
        if amount is None:
            return '0,00'
        return f"{amount:,.2f}".replace(',', ' ').replace('.', ',')

    @staticmethod
    def _amount_to_words_ua(amount):
        """Render a monetary amount in Ukrainian words (грн / коп).

        Used in legal salary certificates where the sum must be written
        in words next to the figures.
        """
        if amount is None:
            return ''
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return ''

        ones_m = ['', 'один', 'два', 'три', 'чотири', "п'ять", 'шість', 'сім', 'вісім', "дев'ять"]
        ones_f = ['', 'одна', 'дві', 'три', 'чотири', "п'ять", 'шість', 'сім', 'вісім', "дев'ять"]
        teens = ['десять', 'одинадцять', 'дванадцять', 'тринадцять', 'чотирнадцять',
                 "п'ятнадцять", 'шістнадцять', 'сімнадцять', 'вісімнадцять', "дев'ятнадцять"]
        tens = ['', '', 'двадцять', 'тридцять', 'сорок', "п'ятдесят",
                'шістдесят', 'сімдесят', 'вісімдесят', "дев'яносто"]
        hundreds = ['', 'сто', 'двісті', 'триста', 'чотириста', "п'ятсот",
                    'шістсот', 'сімсот', 'вісімсот', "дев'ятсот"]

        def _group(n, feminine):
            ones = ones_f if feminine else ones_m
            parts = []
            if n >= 100:
                parts.append(hundreds[n // 100])
                n %= 100
            if 10 <= n < 20:
                parts.append(teens[n - 10])
                n = 0
            if n >= 20:
                parts.append(tens[n // 10])
                n %= 10
            if n > 0:
                parts.append(ones[n])
            return ' '.join(parts)

        def _plural(n, forms):
            n10, n100 = n % 10, n % 100
            if 11 <= n100 <= 14:
                return forms[2]
            if n10 == 1:
                return forms[0]
            if 2 <= n10 <= 4:
                return forms[1]
            return forms[2]

        whole = int(amount)
        kop = int(round((amount - whole) * 100))

        millions = whole // 1_000_000
        thousands = (whole % 1_000_000) // 1000
        units = whole % 1000

        words = []
        if millions:
            words.append(_group(millions, feminine=False))
            words.append(_plural(millions, ['мільйон', 'мільйони', 'мільйонів']))
        if thousands:
            words.append(_group(thousands, feminine=True))
            words.append(_plural(thousands, ['тисяча', 'тисячі', 'тисяч']))
        if units or not words:
            words.append(_group(units, feminine=False) or 'нуль')
        words.append('грн.')
        words.append(f"{kop:02d}")
        words.append('коп.')
        result = ' '.join(words)
        return result[0].upper() + result[1:]

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
