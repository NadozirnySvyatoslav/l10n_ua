from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # === Personal Documents ===
    employee_number = fields.Char(
        string='Personnel Number',
        copy=False,
        help='Personnel number of the employee according to Ukrainian legislation (Табельний номер)')

    def action_generate_employee_number(self):
        """Generate next personnel number from the sequence."""
        for employee in self:
            if not employee.employee_number:
                employee.employee_number = self.env['ir.sequence'].next_by_code('hr.employee.number')

    # RNOKPP is Ukrainian-specific, different from Odoo's identification_id
    rnokpp = fields.Char(
        string='RNOKPP (IPN)', size=10,
        help='Registration Number of the Taxpayer Account Card (Individual Tax Number)')

    # Document type and Ukrainian-specific fields
    document_type = fields.Selection([
        ('passport', 'Passport (old format)'),
        ('id_card', 'ID Card'),
        ('other', 'Other'),
    ], string='Document Type', default='id_card')
    passport_series = fields.Char(string='Passport Series', size=2,
                                   help='For old format passports only')
    # Use Odoo core passport_id field (via hr.version)
    # passport_number - REMOVED, use passport_id from core
    passport_issued_by = fields.Char(string='Issued By', size=100)
    passport_issued_date = fields.Date(string='Issue Date')
    # passport_valid_until - REMOVED, use passport_expiration_date from core
    passport_record_number = fields.Char(string='Record Number', size=14,
                                          help='Unique record number in the register (for ID cards)')

    # === Registration Address ===
    registration_address = fields.Text(string='Registration Address')
    registration_region_id = fields.Many2one(
        'res.country.state', string='Registration Region',
        domain="[('country_id.code', '=', 'UA')]")
    registration_city = fields.Char(string='Registration City')
    registration_zip = fields.Char(string='Registration ZIP', size=5)

    # === Actual Address ===
    actual_address = fields.Text(string='Actual Address')
    actual_same_as_registration = fields.Boolean(
        string='Same as Registration',
        help='Actual address is the same as registration address')

    # === Education ===
    # Use Odoo core fields: study_school (institution), study_field (specialty), certificate (level)
    # education_institution - REMOVED, use study_school from core
    # education_specialty - REMOVED, use study_field from core
    # Keep education_level_id as Many2one for more detailed Ukrainian education levels
    education_level_id = fields.Many2one('hr.education.level', string='Education Level (UA)',
                                          help='Detailed Ukrainian education level classification')
    # Ukrainian-specific diploma details
    diploma_series = fields.Char(string='Diploma Series')
    diploma_number = fields.Char(string='Diploma Number')
    diploma_date = fields.Date(string='Diploma Date')

    # === Military Accounting ===
    military_status = fields.Selection([
        ('liable', 'Liable for Military Service'),
        ('reserved', 'Reserved'),
        ('exempt', 'Exempt'),
        ('not_applicable', 'Not Applicable'),
    ], string='Military Status', default='not_applicable')
    military_category = fields.Selection([
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('removed', 'Removed from Register'),
    ], string='Military Category')
    military_rank_id = fields.Many2one('hr.military.rank', string='Military Rank')
    military_specialty = fields.Char(string='Military Specialty (VOS)',
                                      help='Military Occupational Specialty')
    military_fitness = fields.Selection([
        ('fit', 'Fit for Service'),
        ('limited', 'Limited Fitness'),
        ('unfit', 'Unfit for Service'),
    ], string='Military Fitness')
    military_document_number = fields.Char(string='Military Document Number')
    military_tcc_id = fields.Many2one('hr.military.tcc', string='TCC',
                                       help='Territorial Recruitment Center')
    military_reservation = fields.Boolean(string='Reserved (Booking)')
    military_reservation_until = fields.Date(string='Reserved Until')
    military_reservplus_id = fields.Char(string='Reserv+ ID',
                                          help='Ідентифікатор у системі Резерв+')

    # === Benefits ===
    benefit_ids = fields.Many2many('hr.employee.benefit', string='Benefits')
    disability_group = fields.Selection([
        ('1', 'Group I'),
        ('2', 'Group II'),
        ('3', 'Group III'),
        ('none', 'None'),
    ], string='Disability Group', default='none')
    disability_reason = fields.Char(string='Disability Reason')
    disability_document = fields.Char(string='MSEC Document',
                                       help='Medical-Social Expert Commission document')
    disability_date_from = fields.Date(string='Disability From')
    disability_date_to = fields.Date(string='Disability Until')
    chornobyl_category = fields.Selection([
        ('1', 'Category 1'),
        ('2', 'Category 2'),
        ('3', 'Category 3'),
        ('4', 'Category 4'),
        ('none', 'None'),
    ], string='Chornobyl Category', default='none')
    veteran_status = fields.Selection([
        ('combat', 'Combat Veteran'),
        ('war', 'War Veteran'),
        ('labor', 'Labor Veteran'),
        ('none', 'None'),
    ], string='Veteran Status', default='none')

    # === Family ===
    # Use Odoo core fields: marital (status), spouse_complete_name, spouse_birthdate, children (count)
    # marital_status_ua - REMOVED, use marital from core
    # spouse_name - REMOVED, use spouse_complete_name from core
    # Ukrainian-specific: spouse tax ID
    spouse_rnokpp = fields.Char(string='Spouse RNOKPP', size=10)
    # Detailed children records (Odoo core only has count)
    children_ids = fields.One2many('hr.employee.child', 'employee_id', string='Children')
    children_count = fields.Integer(string='Children Count', compute='_compute_children_count', store=True)
    dependents_count = fields.Integer(string='Dependents Count', compute='_compute_dependents_count', store=True,
                                       help='Number of dependents for PSP calculation')

    # === Work Experience & Bank ===
    hire_date = fields.Date(string='Hire Date')
    work_experience_total = fields.Float(string='Total Work Experience (years)',
                                          help='Total work experience in years')
    work_experience_company = fields.Float(string='Company Experience (years)',
                                            compute='_compute_work_experience_company', store=True)
    insurance_experience = fields.Float(string='Insurance Experience (years)',
                                         help='Insurance experience for sick leave calculation')
    bank_account_id = fields.Many2one('res.partner.bank', string='Bank Account',
                                       help='Bank account for salary payment')

    # === Related fields from hr.job (readonly) ===
    job_kp_code = fields.Char(
        string='KP Code', related='job_id.kp_code', readonly=True, store=True,
        help='Код професії за Класифікатором професій ДК 003:2010')
    job_kp_name = fields.Char(
        string='KP Name', related='job_id.kp_name', readonly=True, store=True,
        help='Назва професії за Класифікатором професій')
    job_work_conditions = fields.Selection(
        related='job_id.work_conditions', readonly=True, store=False,
        string='Work Conditions')
    job_hazard_class = fields.Selection(
        related='job_id.hazard_class', readonly=True, store=False,
        string='Hazard Class')
    job_currency_id = fields.Many2one(
        related='job_id.currency_id', readonly=True, store=False,
        string='Job Currency')
    job_min_salary = fields.Monetary(
        related='job_id.min_salary', readonly=True, store=False,
        currency_field='job_currency_id', string='Min Salary')
    job_max_salary = fields.Monetary(
        related='job_id.max_salary', readonly=True, store=False,
        currency_field='job_currency_id', string='Max Salary')

    @api.depends('children_ids')
    def _compute_children_count(self):
        for employee in self:
            employee.children_count = len(employee.children_ids)

    @api.depends('children_ids', 'children_ids.is_dependent')
    def _compute_dependents_count(self):
        for employee in self:
            employee.dependents_count = len(employee.children_ids.filtered('is_dependent'))

    @api.depends('hire_date')
    def _compute_work_experience_company(self):
        today = date.today()
        for employee in self:
            if employee.hire_date:
                delta = relativedelta(today, employee.hire_date)
                employee.work_experience_company = delta.years + delta.months / 12.0
            else:
                employee.work_experience_company = 0.0

    @api.onchange('actual_same_as_registration')
    def _onchange_actual_same_as_registration(self):
        if self.actual_same_as_registration:
            self.actual_address = self.registration_address

    @api.constrains('rnokpp')
    def _check_rnokpp(self):
        validate_rnokpp = self.env['ir.config_parameter'].sudo().get_param(
            'hr_ua.validate_rnokpp', 'True')
        if validate_rnokpp.lower() == 'true':
            for employee in self:
                if employee.rnokpp and not self._validate_rnokpp(employee.rnokpp):
                    raise ValidationError('Invalid RNOKPP (IPN) checksum!')

    @staticmethod
    def _validate_rnokpp(rnokpp):
        """Validate Ukrainian RNOKPP (IPN) checksum."""
        if not rnokpp or len(rnokpp) != 10 or not rnokpp.isdigit():
            return False
        weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
        checksum = sum(int(rnokpp[i]) * weights[i] for i in range(9))
        control = (checksum % 11) % 10
        return control == int(rnokpp[9])

    @api.constrains('passport_id', 'document_type')
    def _check_passport_number(self):
        """Validate passport/ID number format based on document type."""
        for employee in self:
            if employee.passport_id:
                if employee.document_type == 'passport' and len(employee.passport_id) != 6:
                    raise ValidationError('Old passport number must be 6 digits!')
                if employee.document_type == 'id_card' and len(employee.passport_id) != 9:
                    raise ValidationError('ID card number must be 9 digits!')

    _rnokpp_uniq = models.Constraint(
	'unique(rnokpp, company_id)',
        'RNOKPP (IPN) must be unique!',
    )

    # === Staffing Table / Job filtering ===
    allowed_job_ids = fields.Many2many(
        'hr.job', 
        compute='_compute_allowed_job_ids',
        string='Allowed Jobs (by Staffing Table)'
    )

    @api.depends('department_id')
    def _compute_allowed_job_ids(self):
        for employee in self:
            if employee.department_id:
                # Find approved staffing records for the selected department
                staffing_records = self.env['hr.staffing.table'].search([
                    ('department_id', '=', employee.department_id.id),
                    ('state', '=', 'approved') 
                ])
                employee.allowed_job_ids = staffing_records.mapped('job_id')
            else:
                # If no department is selected, allow all jobs
                employee.allowed_job_ids = self.env['hr.job'].search([])

    @api.onchange('department_id')
    def _onchange_department_clear_job(self):
        """Clears the job position field if it does not belong to the newly selected department"""
        if self.job_id and self.job_id not in self.allowed_job_ids:
            self.job_id = False
