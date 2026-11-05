from odoo import fields, models


class L10nUaMedecinDepartment(models.Model):
    """Відділення стаціонару.

    Мінімальний довідник для прив'язки епізодів стаціонарного лікування.
    Ліжковий фонд (палати, ліжка) і ф. 007/о додаються окремою задачею (#227)
    як розширення цієї ж моделі.
    """
    _name = 'l10n_ua.medecin.department'
    _description = 'Відділення стаціонару'
    _order = 'sequence, name'

    name = fields.Char(string='Назва', required=True)
    code = fields.Char(string='Код')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Заклад', required=True, index=True,
        default=lambda self: self.env.company)
    specialty_id = fields.Many2one(
        'l10n_ua.medecin.specialty', string='Профіль', ondelete='restrict')
    head_id = fields.Many2one(
        'hr.employee', string='Завідувач', ondelete='set null',
        domain="[('company_id', 'in', (company_id, False))]")
    note = fields.Text(string='Примітки')

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'Код відділення має бути унікальним у межах закладу.',
    )
