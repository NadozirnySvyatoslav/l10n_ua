"""4ДФ — об'єднана квартальна звітність з ПДФО/ВЗ/ЄСВ.

Замінила 1ДФ і Д5 з 01.01.2021. Подається щоквартально через
М.Е.Doc / FREDO / Електронний кабінет ДПС.

Форма J0501T01 (юридична особа) / F0501T01 (ФОП).
Нормативка: Наказ Мінфіну № 4 від 13.01.2015 зі змінами.

MVP scope:
- Header model + Appendix 4DF (per person PDFO/ВЗ) + Appendix 1 (ЄСВ summary)
- Appendix 5 (insured persons) і Appendix 6 (hazardous workers) — TODO
- XML export — basic stub; повна валідація по XSD ДПС — окрема задача
"""

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaTax4DF(models.Model):
    _name = 'l10n_ua.tax.4df'
    _description = '4ДФ — об\'єднана звітність ПДФО/ВЗ/ЄСВ'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, quarter desc'

    name = fields.Char(
        compute='_compute_name',
        store=True,
    )
    year = fields.Integer(
        string='Рік',
        required=True,
        default=lambda self: fields.Date.today().year,
        tracking=True,
    )
    quarter = fields.Selection(
        selection=[
            ('1', 'I квартал'),
            ('2', 'II квартал'),
            ('3', 'III квартал'),
            ('4', 'IV квартал'),
        ],
        string='Квартал',
        required=True,
        tracking=True,
    )
    form_code = fields.Selection(
        selection=[
            ('J0501T01', 'J0501T01 — юридична особа'),
            ('F0501T01', 'F0501T01 — ФОП'),
        ],
        string='Код форми',
        default='J0501T01',
        tracking=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id')

    # --- Підстановки додатків ---
    line_4df_ids = fields.One2many(
        'l10n_ua.tax.4df.line.4df',
        'report_id',
        string='Додаток 4ДФ (ПДФО/ВЗ по фізособах)',
    )
    line_t1_ids = fields.One2many(
        'l10n_ua.tax.4df.line.t1',
        'report_id',
        string='Додаток 1 (ЄСВ по фізособах)',
    )

    # --- Підсумки ---
    total_employees = fields.Integer(
        compute='_compute_totals',
        store=True,
    )
    total_accrued = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_pdfo = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_military = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_esv_base = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_esv = fields.Monetary(
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )

    # --- Стан ---
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('generated', 'Згенеровано'),
            ('submitted', 'Подано'),
        ],
        default='draft',
        tracking=True,
        copy=False,
    )
    submission_date = fields.Date(string='Дата подання')
    xml_file = fields.Binary(string='XML-файл', attachment=True, copy=False)
    xml_filename = fields.Char(copy=False)
    notes = fields.Text(string='Примітки')

    _unique_year_quarter_company = models.Constraint(
        'unique(year, quarter, company_id)',
        '4ДФ за цей період вже існує для цієї компанії!',
    )

    @api.depends('year', 'quarter')
    def _compute_name(self):
        for rec in self:
            if rec.year and rec.quarter:
                rec.name = '4ДФ %s Q%s' % (rec.year, rec.quarter)
            else:
                rec.name = _('Нова')

    @api.depends('line_4df_ids', 'line_4df_ids.accrued_amount',
                 'line_4df_ids.pdfo_amount', 'line_4df_ids.military_amount',
                 'line_t1_ids', 'line_t1_ids.esv_base', 'line_t1_ids.esv_amount')
    def _compute_totals(self):
        for rec in self:
            employee_ids = set(rec.line_4df_ids.mapped('employee_id.id'))
            employee_ids.update(rec.line_t1_ids.mapped('employee_id.id'))
            rec.total_employees = len(employee_ids)
            rec.total_accrued = sum(rec.line_4df_ids.mapped('accrued_amount'))
            rec.total_pdfo = sum(rec.line_4df_ids.mapped('pdfo_amount'))
            rec.total_military = sum(rec.line_4df_ids.mapped('military_amount'))
            rec.total_esv_base = sum(rec.line_t1_ids.mapped('esv_base'))
            rec.total_esv = sum(rec.line_t1_ids.mapped('esv_amount'))

    # --- Дії ---

    def _get_quarter_dates(self):
        """Повертає (date_from, date_to) для періоду звіту."""
        self.ensure_one()
        quarter_months = {
            '1': (1, 3),
            '2': (4, 6),
            '3': (7, 9),
            '4': (10, 12),
        }
        first_month, last_month = quarter_months[self.quarter]
        date_from = date(self.year, first_month, 1)
        # Last day of last_month
        if last_month == 12:
            date_to = date(self.year, 12, 31)
        else:
            next_month_first = date(self.year, last_month + 1, 1)
            from dateutil.relativedelta import relativedelta
            date_to = next_month_first - relativedelta(days=1)
        return date_from, date_to

    def action_generate(self):
        """Згенерувати додатки з payslips за квартал."""
        for rec in self:
            if rec.state == 'submitted':
                raise UserError(_('Не можна перегенерувати поданий звіт.'))
            rec.line_4df_ids.unlink()
            rec.line_t1_ids.unlink()
            rec._generate_appendix_4df()
            rec._generate_appendix_t1()
            rec.state = 'generated'
        return True

    def _generate_appendix_4df(self):
        """Додаток 4ДФ — ПДФО/ВЗ по фізособах (наступник 1ДФ)."""
        self.ensure_one()
        Line = self.env['l10n_ua.tax.4df.line.4df']
        date_from, date_to = self._get_quarter_dates()
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', 'in', ['done', 'paid']),
        ])
        by_emp = {}
        for slip in payslips:
            emp_id = slip.employee_id.id
            d = by_emp.setdefault(emp_id, {
                'accrued': 0.0, 'paid': 0.0,
                'pdfo': 0.0, 'military': 0.0,
            })
            d['accrued'] += slip.gross_salary
            d['paid'] += slip.net_salary
            d['pdfo'] += slip.pdfo_amount
            d['military'] += slip.military_tax_amount
        for emp_id, d in by_emp.items():
            employee = self.env['hr.employee'].browse(emp_id)
            date_hire, date_termination = self._employee_period_dates(
                employee, date_from, date_to)
            Line.create({
                'report_id': self.id,
                'employee_id': emp_id,
                'rnokpp': employee.rnokpp or '',
                'income_type': '101',
                'income_sign': '0',
                'accrued_amount': d['accrued'],
                'paid_amount': d['paid'],
                'pdfo_amount': d['pdfo'],
                'military_amount': d['military'],
                'date_hire': date_hire,
                'date_termination': date_termination,
            })

    def _generate_appendix_t1(self):
        """Додаток 1 — Зведена відомість ЄСВ по фізособах."""
        self.ensure_one()
        Line = self.env['l10n_ua.tax.4df.line.t1']
        date_from, date_to = self._get_quarter_dates()
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<=', date_to),
            ('state', 'in', ['done', 'paid']),
        ])
        by_emp = {}
        for slip in payslips:
            emp_id = slip.employee_id.id
            d = by_emp.setdefault(emp_id, {
                'accrued': 0.0, 'esv_base': 0.0, 'esv': 0.0,
                'months': set(),
            })
            d['accrued'] += slip.gross_salary
            d['esv_base'] += slip.esv_base
            d['esv'] += slip.esv_amount
            d['months'].add((slip.date_from.year, slip.date_from.month))
        for emp_id, d in by_emp.items():
            employee = self.env['hr.employee'].browse(emp_id)
            Line.create({
                'report_id': self.id,
                'employee_id': emp_id,
                'rnokpp': employee.rnokpp or '',
                'accrued_amount': d['accrued'],
                'esv_base': d['esv_base'],
                'esv_amount': d['esv'],
                'months_count': len(d['months']),
            })

    @staticmethod
    def _employee_period_dates(employee, date_from, date_to):
        """Повертає (date_hire, date_termination) у межах періоду звіту."""
        date_hire = False
        date_termination = False
        version = employee.current_version_id
        if version:
            start = version.contract_date_start
            end = getattr(version, 'contract_date_end', None)
            if start and date_from <= start <= date_to:
                date_hire = start
            if end and date_from <= end <= date_to:
                date_termination = end
        return date_hire, date_termination

    # --- Стан ---

    def action_submit(self):
        for rec in self:
            if rec.state != 'generated':
                raise UserError(_('Подати можна лише згенерований звіт.'))
            rec.write({
                'state': 'submitted',
                'submission_date': fields.Date.today(),
            })
        return True

    def action_draft(self):
        for rec in self:
            rec.write({
                'state': 'draft',
                'submission_date': False,
            })
        return True

    def action_generate_xml(self):
        """Сформувати XML-файл звіту (заглушка-структура).

        Повна валідація по XSD ДПС/ПФУ — окрема задача (FREDO/М.Е.Doc).
        """
        import base64
        from xml.sax.saxutils import escape
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_('Спочатку згенеруйте звіт з payslips.'))
            rec.xml_file = base64.b64encode(rec._build_xml_bytes())
            rec.xml_filename = '%s_%s_Q%s.xml' % (
                rec.form_code, rec.year, rec.quarter)
        return True

    def _build_xml_bytes(self):
        """Побудувати XML-байти. Структура — спрощена."""
        self.ensure_one()
        from xml.sax.saxutils import escape
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append('<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')
        lines.append('<DECLARHEAD>')
        lines.append('<TIN>%s</TIN>' % escape(
            self.company_id.partner_id.company_registry or ''))
        lines.append('<C_DOC>%s</C_DOC>' % escape(self.form_code or ''))
        lines.append('<PERIOD_MONTH>%s</PERIOD_MONTH>' % (int(self.quarter) * 3))
        lines.append('<PERIOD_YEAR>%s</PERIOD_YEAR>' % self.year)
        lines.append('<C_STI_ORIG>%s</C_STI_ORIG>' % escape(
            self.company_id.name or ''))
        lines.append('</DECLARHEAD>')
        lines.append('<DECLARBODY>')
        # Appendix 4DF — per person
        lines.append('<T1RXXXXG1S>')
        for line in self.line_4df_ids:
            lines.append('<ROW>')
            lines.append('<RNOKPP>%s</RNOKPP>' % escape(line.rnokpp or ''))
            lines.append('<ACCRUED>%.2f</ACCRUED>' % line.accrued_amount)
            lines.append('<PAID>%.2f</PAID>' % line.paid_amount)
            lines.append('<PDFO>%.2f</PDFO>' % line.pdfo_amount)
            lines.append('<MILITARY>%.2f</MILITARY>' % line.military_amount)
            lines.append('<INCOME_TYPE>%s</INCOME_TYPE>' % escape(
                line.income_type or ''))
            if line.date_hire:
                lines.append('<DATE_HIRE>%s</DATE_HIRE>' % line.date_hire)
            if line.date_termination:
                lines.append('<DATE_TERMINATION>%s</DATE_TERMINATION>' %
                             line.date_termination)
            lines.append('</ROW>')
        lines.append('</T1RXXXXG1S>')
        # Appendix 1 — ESV
        lines.append('<T1RXXXXG2S>')
        for line in self.line_t1_ids:
            lines.append('<ROW>')
            lines.append('<RNOKPP>%s</RNOKPP>' % escape(line.rnokpp or ''))
            lines.append('<ACCRUED>%.2f</ACCRUED>' % line.accrued_amount)
            lines.append('<ESV_BASE>%.2f</ESV_BASE>' % line.esv_base)
            lines.append('<ESV>%.2f</ESV>' % line.esv_amount)
            lines.append('<MONTHS>%s</MONTHS>' % line.months_count)
            lines.append('</ROW>')
        lines.append('</T1RXXXXG2S>')
        lines.append('</DECLARBODY>')
        lines.append('</DECLAR>')
        return '\n'.join(lines).encode('utf-8')


class L10nUaTax4DFLine4DF(models.Model):
    _name = 'l10n_ua.tax.4df.line.4df'
    _description = 'Додаток 4ДФ — ПДФО/ВЗ по фізособах'
    _order = 'employee_id'

    report_id = fields.Many2one(
        'l10n_ua.tax.4df',
        string='Звіт',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(related='report_id.company_id', store=True)
    currency_id = fields.Many2one(related='report_id.currency_id')

    employee_id = fields.Many2one(
        'hr.employee',
        string='Працівник',
        required=True,
    )
    rnokpp = fields.Char(
        string='РНОКПП',
        required=True,
        size=10,
    )
    income_type = fields.Char(
        string='Код типу доходу',
        default='101',
        help='Код ознаки доходу (за класифікатором ДПС, типово 101 — зарплата)',
    )
    income_sign = fields.Selection(
        selection=[
            ('0', 'Нараховано і виплачено'),
            ('1', 'Лише нараховано'),
        ],
        string='Ознака доходу',
        default='0',
    )
    accrued_amount = fields.Monetary(
        string='Нараховано',
        currency_field='currency_id',
    )
    paid_amount = fields.Monetary(
        string='Виплачено',
        currency_field='currency_id',
    )
    pdfo_amount = fields.Monetary(
        string='ПДФО',
        currency_field='currency_id',
    )
    military_amount = fields.Monetary(
        string='Військовий збір',
        currency_field='currency_id',
    )
    date_hire = fields.Date(string='Дата прийому (квартал)')
    date_termination = fields.Date(string='Дата звільнення (квартал)')


class L10nUaTax4DFLineT1(models.Model):
    _name = 'l10n_ua.tax.4df.line.t1'
    _description = 'Додаток 1 — ЄСВ по фізособах'
    _order = 'employee_id'

    report_id = fields.Many2one(
        'l10n_ua.tax.4df',
        string='Звіт',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(related='report_id.company_id', store=True)
    currency_id = fields.Many2one(related='report_id.currency_id')

    employee_id = fields.Many2one(
        'hr.employee',
        string='Працівник',
        required=True,
    )
    rnokpp = fields.Char(
        string='РНОКПП',
        required=True,
        size=10,
    )
    accrued_amount = fields.Monetary(
        string='Нараховано (база до обмежень)',
        currency_field='currency_id',
    )
    esv_base = fields.Monetary(
        string='База ЄСВ',
        currency_field='currency_id',
        help='Сума з урахуванням мін/макс обмежень ЄСВ',
    )
    esv_amount = fields.Monetary(
        string='Нараховано ЄСВ',
        currency_field='currency_id',
    )
    months_count = fields.Integer(
        string='Місяців відпрацьовано',
    )
