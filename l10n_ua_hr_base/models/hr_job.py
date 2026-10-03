from odoo import models, fields, api


class HrJob(models.Model):
    _inherit = 'hr.job'

    kp_code = fields.Char(
        string='KP Code', size=10,
        compute='_compute_kp_fields', store=True,
        help='Code from Classifier of Professions (KP 2010)')
    kp_name = fields.Char(
        string='KP Name',
        compute='_compute_kp_fields', store=True,
        help='Name according to Classifier of Professions')
    kp_id = fields.Many2one(
        'hr.kp2010', string='Profession (KP)',
        help='Profession from Classifier of Professions 2010')
    work_conditions = fields.Selection([
        ('normal', 'Normal'),
        ('hazardous', 'Hazardous'),
        ('heavy', 'Heavy'),
    ], string='Work Conditions', default='normal')
    hazard_class = fields.Selection([
        ('1', 'Class 1 (Optimal)'),
        ('2', 'Class 2 (Acceptable)'),
        ('3.1', 'Class 3.1 (Harmful)'),
        ('3.2', 'Class 3.2 (Harmful)'),
        ('3.3', 'Class 3.3 (Harmful)'),
        ('3.4', 'Class 3.4 (Harmful)'),
        ('4', 'Class 4 (Dangerous)'),
    ], string='Hazard Class')
    tariff_grade_id = fields.Many2one(
        'hr.tariff.grade', string='Tariff Grade', check_company=True)
    min_salary = fields.Monetary(
        string='Minimum Salary', currency_field='currency_id',
        help='Minimum salary for this position')
    max_salary = fields.Monetary(
        string='Maximum Salary', currency_field='currency_id',
        help='Maximum salary for this position')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    probation_days = fields.Integer(
        string='Probation Period (days)',
        help='Default probation period in days')

    @api.depends('kp_id')
    def _compute_kp_fields(self):
        for job in self:
            job.kp_code = job.kp_id.code if job.kp_id else False
            job.kp_name = job.kp_id.name if job.kp_id else False

    @api.onchange('kp_id')
    def _onchange_kp_id(self):
        if self.kp_id and self.kp_id.work_conditions:
            self.work_conditions = self.kp_id.work_conditions

    @api.onchange('company_id')
    def _onchange_company_id_ua(self):
        if self.department_id and self.department_id.company_id \
                and self.department_id.company_id != self.company_id:
            self.department_id = False
        if self.tariff_grade_id and self.tariff_grade_id.company_id != self.company_id:
            self.tariff_grade_id = False

    @api.constrains('tariff_grade_id', 'company_id')
    def _check_tariff_grade_company(self):
        # hr.job does not set _check_company_auto, so check_company alone
        # would only narrow the dropdown.
        self._check_company(['tariff_grade_id'])
