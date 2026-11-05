from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    payroll_bank_file_format = fields.Selection(
        selection_add=[('mono_api', 'monobank API (salary registry)')],
        ondelete={'mono_api': 'set default'},
    )
