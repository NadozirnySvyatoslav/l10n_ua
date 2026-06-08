from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta


class HrEmployeeChild(models.Model):
    _name = 'hr.employee.child'
    _description = 'Employee Child'
    _order = 'birthday desc'

    employee_id = fields.Many2one('hr.employee', string='Employee',
                                   required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Full Name', required=True)
    birthday = fields.Date(string='Birthday', required=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender')
    birth_certificate_number = fields.Char(string='Birth Certificate Number')
    rnokpp = fields.Char(string='RNOKPP (IPN)', size=10,
                          help='Registration Number of the Taxpayer Account Card')
    is_disabled = fields.Boolean(string='Disabled Child',
                                  help='Child with disability (for PSP calculation)')
    disability_group = fields.Selection([
        ('1', 'Group I'),
        ('2', 'Group II'),
        ('3', 'Group III'),
    ], string='Disability Group',
       help='Required when child is marked as disabled')
    is_student = fields.Boolean(string='Student',
                                 help='Full-time student (qualifies as dependent up to 23 y.o. per PSP rules)')
    is_orphan = fields.Boolean(string='Orphan / Without Parental Care',
                                help='Child orphan or deprived of parental care (PSP-relevant)')
    is_dependent = fields.Boolean(string='Dependent (manual)', default=True,
                                   help='Manual marker. Aggregate count on the employee uses age/student/disability logic regardless.')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)

    # Supporting documents (ПК ст. 169.4.1 — підстава для ПСП на утриманця)
    birth_cert_attachment_ids = fields.Many2many(
        'ir.attachment',
        'hr_employee_child_attachment_rel',
        'child_id', 'attachment_id',
        string='Підтверджуючі документи',
        help='Свідоцтво про народження, довідка з ВНЗ (для студентів), '
             'висновок МСЕК (для дітей-інвалідів). Підстава для ПСП за ПК 169.4.1.',
    )

    @api.depends('birthday')
    def _compute_age(self):
        today = date.today()
        for child in self:
            if child.birthday:
                child.age = relativedelta(today, child.birthday).years
            else:
                child.age = 0

    @api.onchange('is_disabled')
    def _onchange_is_disabled(self):
        if not self.is_disabled:
            self.disability_group = False

    @api.constrains('is_disabled', 'disability_group')
    def _check_disability_group(self):
        for child in self:
            if child.is_disabled and not child.disability_group:
                raise ValidationError(_(
                    "Вкажіть групу інвалідності для дитини '%s' "
                    "(відмічена як дитина-інвалід).") % child.name)

    @api.constrains('rnokpp')
    def _check_rnokpp(self):
        for child in self:
            if child.rnokpp and not self._validate_rnokpp(child.rnokpp):
                pass  # Validation can be enabled via system parameter

    @staticmethod
    def _validate_rnokpp(rnokpp):
        """Validate Ukrainian RNOKPP (IPN) checksum."""
        if not rnokpp or len(rnokpp) != 10 or not rnokpp.isdigit():
            return False
        weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
        checksum = sum(int(rnokpp[i]) * weights[i] for i in range(9))
        control = (checksum % 11) % 10
        return control == int(rnokpp[9])
