from odoo import models, fields, api


class HrTerminationReason(models.Model):
    _name = 'hr.termination.reason'
    _description = 'Termination Reason'
    _order = 'category, sequence, article'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    
    article = fields.Char(string='Labor Code Article', help='e.g., 36, 38, 40')
    paragraph = fields.Char(string='Paragraph', help='e.g., п. 1, п. 2')
    kzpt_code = fields.Char(
        string='КЗпП Code',
        compute='_compute_kzpt_code',
        store=True,
        index=True,
        help='Normalized "<article>[.<paragraph>]" key for reporting and PFU exchange (e.g. "36.1", "38", "40.3").')
    full_reference = fields.Char(
        string='Full Reference',
        compute='_compute_full_reference',
        store=True
    )
    full_text = fields.Text(string='Full Text for Order')
    description_html = fields.Html(
        string='Legal Description',
        sanitize=True,
        help='Rich description of the legal basis — quoted КЗпП article text, jurisprudence notes, etc.')
    
    category = fields.Selection([
        ('own_will', 'Own Will (Art. 38)'),
        ('agreement', 'By Agreement (Art. 36 p.1)'),
        ('fixed_term', 'Fixed Term Expiry (Art. 36 p.2)'),
        ('transfer', 'Transfer (Art. 36 p.5)'),
        ('employer_initiative', 'Employer Initiative (Art. 40)'),
        ('circumstances', 'Beyond Control (Art. 36 p.3,4,6,7,8)'),
        ('other', 'Other'),
    ], string='Category', required=True, default='other')
    
    requires_compensation = fields.Boolean(
        string='Severance Pay Required',
        help='Whether severance pay is required by law'
    )
    compensation_amount = fields.Selection([
        ('none', 'None'),
        ('one_month', 'One Month Salary'),
        ('two_months', 'Two Months Salary'),
        ('three_months', 'Three Months Salary'),
    ], string='Compensation Amount', default='none')

    notice_days = fields.Integer(
        string='Notice Days',
        help='Days of advance notice required'
    )

    requires_union_consent = fields.Boolean(
        string='Requires Union Consent',
        help='Чи потрібна згода виборного органу первинної профспілкової організації '
             '(ст. 43, 43¹ КЗпП України). При зміні власника на False — застосовується '
             'особлива процедура без згоди профспілки.'
    )
    is_suspension = fields.Boolean(
        string='Suspension (not termination)',
        help='Це відсторонення від роботи (ст. 46 КЗпП), а не звільнення. '
             'Залишається трудовий договір; контракт не закінчується.'
    )
    
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    def _compute_full_reference(self):
        for rec in self:
            parts = []
            if rec.paragraph:
                parts.append(rec.paragraph)
            if rec.article:
                parts.append(f'ст. {rec.article} КЗпП України')
            rec.full_reference = ' '.join(parts) if parts else ''

    @api.depends('article', 'paragraph')
    def _compute_kzpt_code(self):
        for rec in self:
            if not rec.article:
                rec.kzpt_code = False
                continue
            digits = ''.join(ch for ch in (rec.paragraph or '') if ch.isdigit())
            rec.kzpt_code = f"{rec.article}.{digits}" if digits else rec.article

    _unique_code = models.Constraint(
        'unique(code)',
        'Termination reason code must be unique!',
    )
