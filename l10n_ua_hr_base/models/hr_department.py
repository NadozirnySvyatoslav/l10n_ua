from odoo import api, fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    koatuu_code = fields.Char(
        string='KOATUU Code', size=10,
        help='Code of the Classification of Administrative-Territorial Units of Ukraine')
    department_type = fields.Selection([
        ('head', 'Head Office'),
        ('branch', 'Branch'),
        ('representative', 'Representative Office'),
    ], string='Department Type', default='head')
    is_separate_unit = fields.Boolean(
        string='Separate Unit',
        help='Is a separate structural unit (for PFU reporting)')
    edrpou = fields.Char(
        string='EDRPOU', size=8,
        help='EDRPOU code if the branch is a separate legal entity')
    head_employee_id = fields.Many2one(
        'hr.employee', string='Department Head', check_company=True,
        help='Head of the department')

    # hr.department не має _check_company_auto, тому check_company=True лише
    # звужує список вибору у формі. Перевірку під час збереження робимо явно
    # (issue #350), не вмикаючи _check_company_auto для всієї моделі.
    @api.constrains('company_id', 'head_employee_id')
    def _check_head_employee_company(self):
        self._check_company(['head_employee_id'])
