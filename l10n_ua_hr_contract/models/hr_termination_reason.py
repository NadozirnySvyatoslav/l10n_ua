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
    # Розмір вихідної допомоги (ст. 44 КЗпП): кількість середньомісячних
    # заробітків (Порядок № 100, п. 2 абз. 4 і п. 8 — за два останні місяці)
    # або дві мінімальні заробітні плати при призові (п. 3 ст. 36).
    compensation_amount = fields.Selection([
        ('none', 'None'),
        ('one_month', 'One Average Monthly Earnings'),
        ('two_months', 'Two Average Monthly Earnings'),
        ('three_months', 'Three Average Monthly Earnings'),
        ('six_months', 'Six Average Monthly Earnings'),
        ('two_min_wages', 'Two Minimum Wages'),
    ], string='Compensation Amount', default='none',
        help='Severance pay (art. 44 of the Labour Code) as a number of average '
             'monthly earnings, computed from the last two calendar months '
             '(Procedure No. 100), or two minimum wages on conscription.')

    notice_days = fields.Integer(
        string='Notice Days',
        help='Days of advance notice required. A multiple of 30 is read as '
             'calendar months: 60 is the two months of art. 49-2 of the Labour '
             'Code, counted from the notice date.'
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

    # Without the dependency the stored field was computed for nobody: every
    # reason shipped with the module carried an empty «Full Reference» (#158).
    @api.depends('article', 'paragraph')
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

    # Множник середньомісячного заробітку для вихідної допомоги.
    SEVERANCE_MONTHS = {'one_month': 1, 'two_months': 2, 'three_months': 3, 'six_months': 6}

    def _notice_deadline(self, notice_date):
        """Найраніша дата звільнення після попередження notice_date.

        Кратне 30 число днів — календарні місяці (ст. 49-2 КЗпП: «не пізніше
        ніж за два місяці»), інакше — дні.
        """
        self.ensure_one()
        from dateutil.relativedelta import relativedelta
        days = self.notice_days or 0
        if not notice_date or days <= 0:
            return False
        if days % 30 == 0:
            return notice_date + relativedelta(months=days // 30)
        return notice_date + relativedelta(days=days)
