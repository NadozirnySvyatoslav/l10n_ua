"""4ДФ — об'єднана квартальна звітність з ПДФО/ВЗ/ЄСВ.

Замінила 1ДФ і Д5 з 01.01.2021. Подається щоквартально через
М.Е.Doc / FREDO / Електронний кабінет ДПС.

Форма J0501T01 (юридична особа) / F0501T01 (ФОП).
Нормативка: Наказ Мінфіну № 4 від 13.01.2015 зі змінами.

Обсяг:
- Модель заголовка + Додаток 4ДФ (ПДФО/ВЗ по особах) + Додаток 1 (ЄСВ)
- XML Додатка 4ДФ (F0510410/J0510410 v10) — валідний за офіційним XSD ДПС
  (tests/test_xsd_validation.py). Головна форма F0500110/J0500110, Д1/Д5/Д6
  та пакування LINKED_DOCS — наступні інкременти (#142).
"""

import re
from datetime import date
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Додаток 4ДФ = F0510410 (ФОП) / J0510410 (юрособа), версія 10 об'єднаного
# розрахунку. Коди й структура звірені з офіційним XSD ДПС (пакет СКЗ 1.34.0.0).
D4_C_DOC_SUB = '104'
D4_C_DOC_VER = '10'
D4_SOFTWARE = 'Odoo l10n_ua'


class L10nUaTax4DF(models.Model):
    _name = 'l10n_ua.tax.4df'
    _description = '4ДФ — об\'єднана звітність ПДФО/ВЗ/ЄСВ'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
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
        """Відкрити КЕП-підпис і подання 4ДФ до ДПС (l10n_ua.dps.submit.mixin)."""
        return self.action_kep_submit()

    # --- контракт l10n_ua.dps.submit.mixin ---

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'generated':
                raise UserError(_('Подати можна лише згенерований звіт.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати 4ДФ до ДПС')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'submitted',
            'submission_date': fields.Date.today(),
        })
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))

    def action_draft(self):
        for rec in self:
            rec.write({
                'state': 'draft',
                'submission_date': False,
            })
        return True

    def action_generate_xml(self):
        """Сформувати XML Додатка 4ДФ (F0510410/J0510410 v10), валідний за XSD ДПС.

        Наразі формує саме Додаток 4ДФ (per-person ПДФО/ВЗ). Головна форма
        (F0500110/J0500110), Д1/Д5/Д6 і пакування через LINKED_DOCS — окремі
        інкременти (див. #142). Валідність структури підтверджує
        tests/test_xsd_validation.py проти вендореного F0510410.xsd.
        """
        import base64
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_('Спочатку згенеруйте звіт з payslips.'))
            xml = self._render_d4_xml(rec._d4_vals())
            rec.xml_file = base64.b64encode(xml.encode('windows-1251')).decode()
            prefix = 'F0510410' if rec._d4_prefix() == 'F05' else 'J0510410'
            rec.xml_filename = '%s_%s_Q%s.xml' % (prefix, rec.year, rec.quarter)
        return True

    def _d4_prefix(self):
        """C_DOC-префікс додатка: F05 (ФОП) / J05 (юрособа)."""
        return 'F05' if (self.form_code or '').startswith('F') else 'J05'

    def _d4_vals(self):
        """Зібрати значення Додатка 4ДФ із запису (компанія + рядки).

        Обов'язкові реквізити, яких нема в даних, — явна помилка користувачу
        (не підставляємо фейк у документ, який піде до ДПС).
        """
        self.ensure_one()
        company = self.company_id
        edrpou = re.sub(r'\D', '', company.edrpou or '')
        office = company.tax_office_code or ''
        director = company.director_id
        director_rnokpp = re.sub(
            r'\D', '', (director.rnokpp or '') if director else '')

        missing = []
        if not edrpou:
            missing.append(_('код ЄДРПОУ/РНОКПП компанії'))
        if not company.katottg:
            missing.append(_('КАТОТТГ компанії'))
        if not director_rnokpp:
            missing.append(_('РНОКПП керівника (director_id)'))
        if missing:
            raise UserError(_(
                'Для формування 4ДФ заповніть: %s.') % ', '.join(missing))

        month = int(self.quarter) * 3
        persons = []
        for line in self.line_4df_ids:
            persons.append({
                'rnokpp': re.sub(r'\D', '', line.rnokpp or ''),
                'income_accrued': line.accrued_amount,
                'income_paid': line.paid_amount,
                'pdfo_accrued': line.pdfo_amount,
                'pdfo_paid': line.pdfo_amount,
                'mil_accrued': line.military_amount,
                'mil_paid': line.military_amount,
                'income_code': re.sub(r'\D', '', line.income_type or '101'),
                'date_hire': line.date_hire,
                'date_term': line.date_termination,
                'ozn': '1' if line.income_sign == '1' else '0',
            })
        return {
            'prefix': self._d4_prefix(),
            'tin': edrpou,
            'doc_type': 0,
            'doc_cnt': 1,
            'c_reg': office[:2],
            'c_raj': office[2:4],
            'period_month': month,
            'period_type': 2,  # квартальна
            'period_year': self.year,
            'c_sti_orig': office,
            'doc_stan': 1,
            'd_fill': date.today().strftime('%d%m%Y'),
            'hzy': self.year,
            'hzm': month,
            'hnum': 1,
            'hname': company.name or '',
            'htin': edrpou,
            'hkatottg': company.katottg,
            'hkbos': director_rnokpp,
            'hbos': director.name or '',
            'persons': persons,
        }

    @api.model
    def _render_d4_xml(self, vals):
        """Рендер XML Додатка 4ДФ (F0510410/J0510410 v10) з dict значень.

        Стейтлес (лише ``vals``) — щоб валідацію проти офіційного XSD можна
        було проганяти без залежності від наявних записів. Кодування —
        windows-1251 (як приймає ДПС). Порядок і склад елементів звірені з
        F0510410.xsd (DBody: HZ, HZY, HZM, HNUM, HNAME, HTIN, HKATOTTG,
        лічильники, стовпці T1RXXXXG02..G09 по особах, підсумки, HFILL,
        HKBOS, HBOS).
        """
        def esc(v):
            return escape(str(v or ''))

        def num(v):
            return '%.2f' % (v or 0.0)

        def dt(v):
            return v.strftime('%d%m%Y') if v else None

        persons = vals.get('persons') or []
        n = len(persons)

        # Стовпці таблиці 1 — column-major (усі значення одного стовпця підряд,
        # ROWNUM = порядковий номер особи), як вимагає послідовність у XSD.
        def column(tag, key, fmt):
            rows = []
            for i, p in enumerate(persons, 1):
                val = p.get(key)
                if val in (None, ''):
                    continue
                rows.append('        <%s ROWNUM="%d">%s</%s>' % (
                    tag, i, fmt(val), tag))
            return '\n'.join(rows)

        cols = [
            column('T1RXXXXG02', 'rnokpp', lambda v: esc(v)),
            column('T1RXXXXG03A', 'income_accrued', num),
            column('T1RXXXXG03', 'income_paid', num),
            column('T1RXXXXG04A', 'pdfo_accrued', num),
            column('T1RXXXXG04', 'pdfo_paid', num),
            column('T1RXXXXG5A', 'mil_accrued', num),
            column('T1RXXXXG5', 'mil_paid', num),
            column('T1RXXXXG05', 'income_code', lambda v: esc(v)),
            column('T1RXXXXG06D', 'date_hire', dt),
            column('T1RXXXXG07D', 'date_term', dt),
            column('T1RXXXXG09', 'ozn', lambda v: esc(v)),
        ]
        table = '\n'.join(c for c in cols if c)

        # Підсумки розділу I (всього нараховано/виплачено/утримано).
        tot_inc_a = sum(p['income_accrued'] for p in persons)
        tot_inc = sum(p['income_paid'] for p in persons)
        tot_pdfo_a = sum(p['pdfo_accrued'] for p in persons)
        tot_pdfo = sum(p['pdfo_paid'] for p in persons)
        tot_mil_a = sum(p['mil_accrued'] for p in persons)
        tot_mil = sum(p['mil_paid'] for p in persons)

        xml = f'''<?xml version="1.0" encoding="windows-1251"?>
<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="{vals['prefix'][0]}0510410.xsd">
    <DECLARHEAD>
        <TIN>{esc(vals['tin'])}</TIN>
        <C_DOC>{vals['prefix']}</C_DOC>
        <C_DOC_SUB>{D4_C_DOC_SUB}</C_DOC_SUB>
        <C_DOC_VER>{D4_C_DOC_VER}</C_DOC_VER>
        <C_DOC_TYPE>{vals['doc_type']}</C_DOC_TYPE>
        <C_DOC_CNT>{vals['doc_cnt']}</C_DOC_CNT>
        <C_REG>{esc(vals['c_reg'])}</C_REG>
        <C_RAJ>{esc(vals['c_raj'])}</C_RAJ>
        <PERIOD_MONTH>{vals['period_month']}</PERIOD_MONTH>
        <PERIOD_TYPE>{vals['period_type']}</PERIOD_TYPE>
        <PERIOD_YEAR>{vals['period_year']}</PERIOD_YEAR>
        <C_STI_ORIG>{esc(vals['c_sti_orig'])}</C_STI_ORIG>
        <C_DOC_STAN>{vals['doc_stan']}</C_DOC_STAN>
        <D_FILL>{vals['d_fill']}</D_FILL>
        <SOFTWARE>{D4_SOFTWARE}</SOFTWARE>
    </DECLARHEAD>
    <DECLARBODY>
        <HZ>1</HZ>
        <HZY>{vals['hzy']}</HZY>
        <HZM>{vals['hzm']}</HZM>
        <HNUM>{vals['hnum']}</HNUM>
        <HNAME>{esc(vals['hname'])}</HNAME>
        <HTIN>{esc(vals['htin'])}</HTIN>
        <HKATOTTG>{esc(vals['hkatottg'])}</HKATOTTG>
        <R00G01I>{n}</R00G01I>
        <R00G02I>{n}</R00G02I>
{table}
        <R01G03A>{num(tot_inc_a)}</R01G03A>
        <R01G03>{num(tot_inc)}</R01G03>
        <R01G04A>{num(tot_pdfo_a)}</R01G04A>
        <R01G04>{num(tot_pdfo)}</R01G04>
        <R01G5A>{num(tot_mil_a)}</R01G5A>
        <R01G5>{num(tot_mil)}</R01G5>
        <HFILL>{vals['d_fill']}</HFILL>
        <HKBOS>{esc(vals['hkbos'])}</HKBOS>
        <HBOS>{esc(vals['hbos'])}</HBOS>
    </DECLARBODY>
</DECLAR>'''
        return xml


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
