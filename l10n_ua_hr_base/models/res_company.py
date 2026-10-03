from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Реєстраційні реквізити (ЄДРПОУ, КОАТУУ, КАТОТТГ, код ДПІ, код ПФУ,
    # КВЕД, форма власності, юридична адреса) переїхали в
    # `l10n_ua_company_base`: вони потрібні податковому й бухгалтерському
    # блокам, які кадровий модуль не тягнуть і тягнути не мають (#292).
    # Тут лишається те, що справді кадрове.

    director_id = fields.Many2one(
        'hr.employee', string='Director',
        help='Company director for document signing')
    accountant_id = fields.Many2one(
        'hr.employee', string='Chief Accountant',
        help='Chief accountant for document signing')
    hr_manager_id = fields.Many2one(
        'hr.employee', string='HR Manager',
        help='HR department head for document signing')
    military_officer_id = fields.Many2one(
        'hr.employee', string='Відповідальний за військовий облік',
        help='Особа, відповідальна за ведення військового обліку. Підписує '
             'Списки персонального військового обліку та відомість '
             'оперативного обліку (п. 40 Порядку № 1487), і саме її кадровий '
             'модуль підставляє у друковані форми за замовчуванням.')

    # Staffing table settings
    wage_from_staffing = fields.Selection([
        ('none', 'Do not use'),
        ('suggest', 'Suggest (fill on selection)'),
        ('fallback', 'Fallback (use if wage is 0)'),
        ('both', 'Both (suggest + fallback)'),
    ], string='Wage from Staffing Table',
       default='both',
       help='How to use salary from staffing table:\n'
            '- Do not use: ignore staffing table salary\n'
            '- Suggest: auto-fill wage when selecting staffing position\n'
            '- Fallback: use staffing salary in payslip if contract wage is 0\n'
            '- Both: suggest on selection + fallback in payslip')

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        self.env['hr.tariff.grade']._seed_company_grades(companies)
        return companies
