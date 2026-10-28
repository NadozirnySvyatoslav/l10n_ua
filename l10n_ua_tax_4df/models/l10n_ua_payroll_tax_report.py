"""Податковий розрахунок ЮО (J0500111, версія 11) — пакет для подання до ДПС.

Головна форма J0500111 з додатками Д1 (J0510111, ЄСВ по застрахованих
особах) і Д4 (J0510411, ПДФО і ВЗ по фізособах) — одним пакетом, пов'язаним
через LINKED_DOCS (наказ Мінфіну № 4 від 13.01.2015 у ред. наказу № 243 від
07.05.2026, чинна з 17.07.2026). Юрособа подає розрахунок щомісяця.

Дані Д1 — з документа «Д5» (hr.report.d5) того ж місяця: він уже збирає
застрахованих осіб із розрахункових листів, а користувач може там
доправити дні лікарняних/відпусток. Д4 збирається тут помісячно з тих самих
листів. Головна форма рахується з рядків Д1, щоб розділ I збігався з
підсумками додатка.

ФОП-роботодавець (F0500111, квартал із колонками по місяцях) — окремий крок.
"""
import base64
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

SOFTWARE = 'Odoo l10n_ua'
MAIN_FORM = ('J05', '001', '11')
D1_FORM = ('J05', '101', '11')
D4_FORM = ('J05', '104', '11')

# Категорія рядка Д5 -> ставка ЄСВ для розділу I головної форми.
# '3' — працівник з інвалідністю (8,41 %, рядки 2.2/3.2), решта — 22 %.
DISABLED_CATEGORY = '3'
# '2' — договір ЦПХ/гіг-контракт: дохід у рядку 1.2 і код доходу 102 у Д4.
CIVIL_CATEGORY = '2'
ESV_RATE = 0.22


def _dec2(value):
    return '%.2f' % float_round(value or 0.0, precision_digits=2)


def dps_filename(head):
    """Ім'я файлу за наказом № 729 — з тих самих реквізитів, що й DECLARHEAD.

    Потрібне до рендеру: головна форма і додатки посилаються одне на одного
    в LINKED_DOCS, тож імена мають бути відомі наперед.
    """
    return '%s%s%s%s%s%s%s%s%s%s%s%s%s.xml' % (
        str(head['c_reg']).zfill(2), str(head['c_raj']).zfill(2), str(head['tin']).zfill(10),
        head['form'][0], head['form'][1], head['form'][2].zfill(2),
        head['c_doc_stan'], str(head['c_doc_type']).zfill(2), str(head['c_doc_cnt']).zfill(7),
        head['period_type'], str(head['period_month']).zfill(2), head['period_year'],
        str(head['c_sti_orig']).zfill(4))


def linked_docs_xml(linked):
    """LINKED_DOCS для DECLARHEAD: ``linked`` — [(form, filename, TYPE)].

    TYPE 1 — додаток до цього документа, 2 — головний документ пакета.
    """
    if not linked:
        return ''
    return '<LINKED_DOCS>%s</LINKED_DOCS>' % ''.join(
        '<DOC NUM="%s" TYPE="%s"><C_DOC>%s</C_DOC><C_DOC_SUB>%s</C_DOC_SUB>'
        '<C_DOC_VER>%s</C_DOC_VER><C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>1</C_DOC_CNT>'
        '<C_DOC_STAN>1</C_DOC_STAN><FILENAME>%s</FILENAME></DOC>'
        % (num, link_type, form[0], form[1], form[2], fname[:-4] + '.XML')
        for num, (form, fname, link_type) in enumerate(linked, 1))


class L10nUaPayrollTaxReport(models.Model):
    _name = 'l10n_ua.payroll.tax.report'
    _description = 'Податковий розрахунок (ПДФО, ВЗ, ЄСВ)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'year desc, month desc, number desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    year = fields.Integer(
        string='Рік', required=True, default=lambda self: fields.Date.today().year,
        tracking=True)
    month = fields.Selection(
        [(str(m), str(m)) for m in range(1, 13)], string='Місяць', required=True,
        default=lambda self: str((fields.Date.today().replace(day=1) - timedelta(days=1)).month),
        tracking=True)
    number = fields.Integer(
        string='Номер розрахунку', default=1, required=True,
        help='Порядковий номер Розрахунку за цей звітний період у хронологічному '
             'порядку незалежно від типу (рядок 02 форми).')
    state = fields.Selection([
        ('draft', 'Чернетка'),
        ('calculated', 'Розраховано'),
        ('submitted', 'Подано'),
    ], string='Стан', default='draft', tracking=True, copy=False)

    d5_report_id = fields.Many2one(
        'hr.report.d5', string='Відомість Д1 (ЄСВ)', copy=False, readonly=True,
        help='Документ «Д5» того ж місяця — з нього береться додаток Д1. '
             'Дні лікарняних і відпусток правте в ньому.')
    d4_line_ids = fields.One2many(
        'l10n_ua.payroll.tax.report.d4.line', 'report_id', string='Додаток 4ДФ (Д4)',
        copy=False)

    headcount_avg = fields.Integer(
        string='Середньооблікова кількість штатних працівників',
        help='Рядок 091. Заповнюється за даними кадрового обліку; за замовчуванням — '
             'кількість працівників, яким нараховано зарплату.')
    headcount_disabled = fields.Integer(
        string='з них — з інвалідністю', help='Рядок 091.1.')
    new_jobs = fields.Integer(
        string='Створено нових робочих місць', help='Рядок 111.')

    # Розділ I — з рядків Д1, не зберігається: джерело правди — Д1.
    r01_income = fields.Monetary(string='1. Нараховано доходу', compute='_compute_section1')
    r011_salary = fields.Monetary(string='1.1 Заробітна плата', compute='_compute_section1')
    r012_civil = fields.Monetary(string='1.2 Винагорода за ЦПХ', compute='_compute_section1')
    r02_base = fields.Monetary(string='2. База ЄСВ', compute='_compute_section1')
    r021_base22 = fields.Monetary(string='2.1 База 22 %', compute='_compute_section1')
    r022_base841 = fields.Monetary(string='2.2 База 8,41 %', compute='_compute_section1')
    r025_extra = fields.Monetary(string='2.5 Додаткова база (до мінімальної)',
                                 compute='_compute_section1')
    r03_esv = fields.Monetary(string='3. Нараховано ЄСВ', compute='_compute_section1')
    r031_esv22 = fields.Monetary(string='3.1 ЄСВ 22 %', compute='_compute_section1')
    r032_esv841 = fields.Monetary(string='3.2 ЄСВ 8,41 %', compute='_compute_section1')
    r035_esv_extra = fields.Monetary(string='3.5 ЄСВ на доплату до мінімальної',
                                     compute='_compute_section1')
    r092_count = fields.Integer(string='092. Працівників із нарахуванням',
                                compute='_compute_section1')
    total_pdfo = fields.Monetary(string='ПДФО (Д4)', compute='_compute_d4_totals')
    total_military = fields.Monetary(string='Військовий збір (Д4)', compute='_compute_d4_totals')

    submission_date = fields.Date(string='Дата подання', copy=False)
    xml_file = fields.Binary(string='XML розрахунку', attachment=True, copy=False)
    xml_filename = fields.Char(copy=False)
    d1_xml_file = fields.Binary(string='XML Д1', attachment=True, copy=False)
    d1_xml_filename = fields.Char(copy=False)
    d4_xml_file = fields.Binary(string='XML Д4', attachment=True, copy=False)
    d4_xml_filename = fields.Char(copy=False)

    _unique_period_number = models.Constraint(
        'unique(company_id, year, month, number)',
        'Розрахунок з таким номером за цей місяць уже є.',
    )

    @api.depends('year', 'month', 'number')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Податковий розрахунок %(month)s.%(year)s №%(num)s',
                         month=(rec.month or '').zfill(2), year=rec.year, num=rec.number)

    # ------------------------------------------------------------------ дані

    def _period(self):
        """(перший день місяця, перший день наступного) — як у пошуку Д5."""
        self.ensure_one()
        date_from = date(self.year, int(self.month), 1)
        date_to = (date_from + timedelta(days=32)).replace(day=1)
        return date_from, date_to

    def _section1(self):
        """Розділ I головної форми з рядків Д1.

        Рядок 3 дорівнює сумі гр. 20 Д1 (ЄСВ по особах), а не добутку бази на
        ставку: так розрахунок не розходиться з додатком на копійки
        округлення по кожній особі.
        """
        self.ensure_one()
        lines = self.d5_report_id.line_ids
        res = dict.fromkeys(('salary', 'civil', 'base22', 'base841', 'extra',
                             'esv22', 'esv841', 'esv_extra'), 0.0)
        employees = set()
        for line in lines:
            diff = line.min_wage_diff or 0.0
            gross = line.gross_amount or line.esv_base
            if line.category == CIVIL_CATEGORY:
                res['civil'] += gross
            else:
                res['salary'] += gross
                employees.add(line.employee_id.id or line.rnokpp)
            base = (line.esv_base or 0.0) - diff
            extra_esv = float_round(diff * ESV_RATE, precision_digits=2)
            res['extra'] += diff
            res['esv_extra'] += extra_esv
            if line.category == DISABLED_CATEGORY:
                res['base841'] += base
                res['esv841'] += (line.esv_amount or 0.0) - extra_esv
            else:
                res['base22'] += base
                res['esv22'] += (line.esv_amount or 0.0) - extra_esv
        res = {k: float_round(v, precision_digits=2) for k, v in res.items()}
        res['income'] = res['salary'] + res['civil']
        res['base'] = res['base22'] + res['base841'] + res['extra']
        res['esv'] = res['esv22'] + res['esv841'] + res['esv_extra']
        res['count'] = len(employees)
        return res

    @api.depends('d5_report_id.line_ids')
    def _compute_section1(self):
        for rec in self:
            s = rec._section1()
            rec.update({
                'r01_income': s['income'], 'r011_salary': s['salary'], 'r012_civil': s['civil'],
                'r02_base': s['base'], 'r021_base22': s['base22'],
                'r022_base841': s['base841'], 'r025_extra': s['extra'],
                'r03_esv': s['esv'], 'r031_esv22': s['esv22'], 'r032_esv841': s['esv841'],
                'r035_esv_extra': s['esv_extra'], 'r092_count': s['count'],
            })

    @api.depends('d4_line_ids.pdfo_accrued', 'd4_line_ids.mil_accrued')
    def _compute_d4_totals(self):
        for rec in self:
            rec.total_pdfo = sum(rec.d4_line_ids.mapped('pdfo_accrued'))
            rec.total_military = sum(rec.d4_line_ids.mapped('mil_accrued'))

    # ------------------------------------------------------------------ дії

    def action_calculate(self):
        """Зібрати Д1 (через Д5 місяця) і Д4 з проведених розрахункових листів."""
        for rec in self:
            if rec.state == 'submitted':
                raise UserError(_('Поданий розрахунок не перераховується.'))
            rec._calculate_d1()
            rec._calculate_d4()
            vals = {'state': 'calculated', 'xml_file': False, 'xml_filename': False,
                    'd1_xml_file': False, 'd1_xml_filename': False,
                    'd4_xml_file': False, 'd4_xml_filename': False}
            if not rec.headcount_avg:
                vals['headcount_avg'] = rec._section1()['count']
            rec.write(vals)
        return True

    def _calculate_d1(self):
        """Знайти або створити Д5 місяця і перегенерувати його рядки.

        Д5 належить кадровому модулю, права на нього — у кадровиків; бухгалтер,
        який формує розрахунок, лише запускає збір даних, тож sudo.
        """
        self.ensure_one()
        D5 = self.env['hr.report.d5'].sudo()
        d5 = self.d5_report_id.sudo() or D5.search([
            ('company_id', '=', self.company_id.id),
            ('year', '=', self.year), ('month', '=', self.month),
        ], limit=1)
        if not d5:
            d5 = D5.create({'company_id': self.company_id.id,
                            'year': self.year, 'month': self.month})
        if d5.state == 'submitted':
            raise UserError(_('Відомість Д5 за цей місяць уже позначена поданою.'))
        d5.action_generate()
        self.d5_report_id = d5

    def _calculate_d4(self):
        """Д4 помісячно: дохід, ПДФО і ВЗ по фізособах з проведених листів.

        Виплачені суми прирівнюються до нарахованих (зарплату виплачено у
        звітному місяці); інший випадок правиться в рядках вручну.
        """
        self.ensure_one()
        self.d4_line_ids.unlink()
        date_from, date_to = self._period()
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<', date_to),
            ('state', '=', 'done'),
        ])
        by_key = {}
        for slip in payslips:
            version = slip.version_id
            civil = bool(version) and getattr(version, 'contract_type_ua', '') in ('civil', 'gig')
            key = (slip.employee_id.id, '102' if civil else '101')
            d = by_key.setdefault(key, {'income': 0.0, 'pdfo': 0.0, 'mil': 0.0})
            d['income'] += slip.gross_salary or 0.0
            d['pdfo'] += slip.pdfo_amount or 0.0
            d['mil'] += slip.military_tax_amount or 0.0
        Report4df = self.env['l10n_ua.tax.4df']
        month_end = date_to - timedelta(days=1)
        lines = []
        for (emp_id, code), d in sorted(by_key.items()):
            employee = self.env['hr.employee'].browse(emp_id)
            date_hire, date_term = Report4df._employee_period_dates(
                employee, date_from, month_end)
            lines.append({
                'report_id': self.id, 'employee_id': emp_id,
                'rnokpp': employee.rnokpp or '', 'income_code': code,
                'income_accrued': d['income'], 'income_paid': d['income'],
                'pdfo_accrued': d['pdfo'], 'pdfo_paid': d['pdfo'],
                'mil_accrued': d['mil'], 'mil_paid': d['mil'],
                'date_hire': date_hire, 'date_term': date_term,
            })
        self.env['l10n_ua.payroll.tax.report.d4.line'].create(lines)

    def action_draft(self):
        self.write({'state': 'draft', 'submission_date': False})
        return True

    # ------------------------------------------------------------------ XML

    def _tin(self):
        return re.sub(r'\D', '', self.company_id.edrpou or self.company_id.company_registry or '')

    def _office_code(self):
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        return re.sub(r'\D', '', (office.code if office else '') or company.tax_office_code or '')

    def _head(self, form):
        office = self._office_code()
        return {
            'form': form, 'tin': self._tin(),
            'c_doc_type': 0, 'c_doc_cnt': 1, 'c_doc_stan': 1,
            'c_reg': office[:2], 'c_raj': office[2:4], 'c_sti_orig': office,
            'period_type': 1, 'period_month': int(self.month), 'period_year': self.year,
        }

    def _xml_problems(self):
        self.ensure_one()
        company = self.company_id
        problems = []
        if self.state == 'draft':
            problems.append(_('розрахунок не розраховано (кнопка «Розрахувати»)'))
        if not self._tin():
            problems.append(_('код ЄДРПОУ компанії'))
        if len(self._office_code()) != 4:
            problems.append(_('код ДПІ компанії (4 цифри)'))
        if not company.katottg:
            problems.append(_('КАТОТТГ компанії'))
        if not re.fullmatch(r'\d{5}', company.zip or ''):
            problems.append(_('поштовий індекс компанії (5 цифр)'))
        if not company.l10n_ua_tax_office_id:
            problems.append(_('податковий орган компанії (куди подається розрахунок)'))
        director = company.director_id
        if not (director and director.name and re.sub(r'\D', '', director.rnokpp or '')):
            problems.append(_('керівник компанії з РНОКПП (director_id)'))
        if company.l10n_ua_is_fop:
            problems.append(_('ФОП подає квартальний F0500111 — цей документ лише для юросіб'))
        return problems

    def action_generate_xml(self):
        for rec in self:
            problems = rec._xml_problems()
            if problems:
                raise UserError(_('Неможливо сформувати Податковий розрахунок:\n• %s')
                                % '\n• '.join(problems))
            main_head = rec._head(MAIN_FORM)
            main_name = dps_filename(main_head)
            back = [(MAIN_FORM, main_name, 2)]
            annexes = []
            if rec.d5_report_id.line_ids:
                head = rec._head(D1_FORM)
                annexes.append(('d1', D1_FORM, dps_filename(head), rec._render_d1(back)))
            if rec.d4_line_ids:
                head = rec._head(D4_FORM)
                annexes.append(('d4', D4_FORM, dps_filename(head), rec._render_d4(back)))
            if not annexes:
                raise UserError(_('Немає даних для додатків: за місяць не знайдено '
                                  'проведених розрахункових листів.'))
            linked = [(form, fname, 1) for _k, form, fname, _x in annexes]
            main_xml = rec._render_main(linked, {key for key, *_r in annexes})
            vals = {'xml_file': base64.b64encode(main_xml),
                    'xml_filename': dps_standard_filename(main_xml) or main_name,
                    'd1_xml_file': False, 'd1_xml_filename': False,
                    'd4_xml_file': False, 'd4_xml_filename': False}
            for key, _form, fname, xml in annexes:
                vals.update({f'{key}_xml_file': base64.b64encode(xml),
                             f'{key}_xml_filename': dps_standard_filename(xml) or fname})
            rec.write(vals)
        return True

    def _render_d1(self, linked):
        d5 = self.d5_report_id.sudo()
        vals = d5._d1_vals()
        office = self._office_code()
        # Реквізити шапки — ті самі, з яких рахувалося ім'я файлу в LINKED_DOCS.
        vals.update(tin=self._tin(), c_reg=office[:2], c_raj=office[2:4], c_sti_orig=office,
                    linked_xml=linked_docs_xml(linked))
        return d5._render_d1_xml(vals).encode('windows-1251', errors='xmlcharrefreplace')

    def _render_d4(self, linked):
        company = self.company_id
        director = company.director_id
        office = self._office_code()
        persons = [{
            'rnokpp': re.sub(r'\D', '', line.rnokpp or ''),
            'income_accrued': line.income_accrued, 'income_paid': line.income_paid,
            'pdfo_accrued': line.pdfo_accrued, 'pdfo_paid': line.pdfo_paid,
            'mil_accrued': line.mil_accrued, 'mil_paid': line.mil_paid,
            'income_code': re.sub(r'\D', '', line.income_code or '101'),
            'date_hire': line.date_hire, 'date_term': line.date_term,
            'ozn': '0',
        } for line in self.d4_line_ids]
        vals = {
            'prefix': 'J05', 'tin': self._tin(), 'doc_type': 0, 'doc_cnt': 1,
            'c_reg': office[:2], 'c_raj': office[2:4], 'c_sti_orig': office,
            'period_month': int(self.month), 'period_type': 1, 'period_year': self.year,
            'doc_stan': 1, 'd_fill': date.today().strftime('%d%m%Y'),
            'hzy': self.year, 'hzm': int(self.month), 'hnum': self.number,
            'hname': company._l10n_ua_dps_name(), 'htin': self._tin(),
            'hkatottg': company.katottg,
            'hkbos': re.sub(r'\D', '', director.rnokpp or ''), 'hbos': director.name or '',
            'persons': persons,
            'linked_xml': linked_docs_xml(linked),
        }
        xml = self.env['l10n_ua.tax.4df']._render_d4_xml(vals)
        return xml.encode('windows-1251', errors='xmlcharrefreplace')

    def _render_main(self, linked, keys):
        """Головна форма J0500111: шапка, розділ 06/08/09, розділ I, підписанти.

        Порядок тегів — як у xs:sequence схеми; порожні необов'язкові рядки
        не виводяться.
        """
        self.ensure_one()
        company = self.company_id
        director = company.director_id
        accountant = company.accountant_id if 'accountant_id' in company._fields else False
        head = self._head(MAIN_FORM)
        s = self._section1()
        address = ', '.join(filter(None, [company.zip, company.state_id.name, company.city,
                                          company.street, company.street2]))

        def tag(name, value):
            return f'<{name}>{value}</{name}>'

        body = [
            tag('HZ', 1), tag('HZY', self.year), tag('HZM', int(self.month)),
            tag('HNUM', self.number), tag('HNAME', escape(company._l10n_ua_dps_name())),
            tag('HTIN', self._tin()), tag('HKATOTTG', escape(company.katottg)),
            tag('HLOC', escape(address)), tag('HZIP', company.zip),
        ]
        if company.phone:
            body.append(tag('HTEL', escape(company.phone)))
        if company.email:
            body.append(tag('HEMAIL', escape(company.email)))
        body.append(tag('HSTI', escape(company.l10n_ua_tax_office_id.name)))
        if 'd1' in keys:
            body.append(tag('R061G3', 1))
        if 'd4' in keys:
            body.append(tag('R064G3', 1))
        body.append(tag('R081G3', 1))
        counts = [('R091G3', self.headcount_avg), ('R0911G3', self.headcount_disabled),
                  ('R092G3', s['count']), ('R111G3', self.new_jobs)]
        body += [tag(name, value) for name, value in counts if value]
        rows = [
            ('R0101G3', s['income']), ('R01011G3', s['salary']), ('R01012G3', s['civil']),
            ('R0102G3', s['base']), ('R01021G3', s['base22']), ('R01022G3', s['base841']),
            ('R01025G3', s['extra']),
            ('R0103G3', s['esv']), ('R01031G3', s['esv22']), ('R01032G3', s['esv841']),
            ('R010321G3', float_round(s['base841'] * ESV_RATE, precision_digits=2)),
            ('R01035G3', s['esv_extra']),
            ('R0107G3', s['esv']),
        ]
        body += [tag(name, _dec2(value)) for name, value in rows
                 if float_round(value or 0.0, precision_digits=2)]
        body += [tag('HFILL', date.today().strftime('%d%m%Y')),
                 tag('HKBOS', re.sub(r'\D', '', director.rnokpp or '')),
                 tag('HBOS', escape(director.name or ''))]
        acc_rnokpp = re.sub(r'\D', '', (accountant.rnokpp or '') if accountant else '')
        if accountant and accountant.name and acc_rnokpp:
            body += [tag('HKBUH', acc_rnokpp), tag('HBUH', escape(accountant.name))]
        head_xml = (
            '<DECLARHEAD>'
            f'<TIN>{head["tin"]}</TIN><C_DOC>{MAIN_FORM[0]}</C_DOC>'
            f'<C_DOC_SUB>{MAIN_FORM[1]}</C_DOC_SUB><C_DOC_VER>{MAIN_FORM[2]}</C_DOC_VER>'
            f'<C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>1</C_DOC_CNT>'
            f'<C_REG>{head["c_reg"]}</C_REG><C_RAJ>{head["c_raj"]}</C_RAJ>'
            f'<PERIOD_MONTH>{head["period_month"]}</PERIOD_MONTH><PERIOD_TYPE>1</PERIOD_TYPE>'
            f'<PERIOD_YEAR>{head["period_year"]}</PERIOD_YEAR>'
            f'<C_STI_ORIG>{head["c_sti_orig"]}</C_STI_ORIG><C_DOC_STAN>1</C_DOC_STAN>'
            f'{linked_docs_xml(linked)}'
            f'<D_FILL>{date.today():%d%m%Y}</D_FILL><SOFTWARE>{SOFTWARE}</SOFTWARE>'
            '</DECLARHEAD>')
        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               f'xsi:noNamespaceSchemaLocation="{"".join(MAIN_FORM)}.xsd">'
               f'{head_xml}<DECLARBODY>{"".join(body)}</DECLARBODY></DECLAR>')
        return xml.encode('windows-1251', errors='xmlcharrefreplace')

    def _attachment_files(self):
        self.ensure_one()
        return [(key, self[f'{key}_xml_file'], self[f'{key}_xml_filename'])
                for key in ('d1', 'd4') if self[f'{key}_xml_file']]

    # ------------------------------------------------- контракт dps.submit.mixin

    def action_submit(self):
        return self.action_kep_submit()

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Подати можна лише розрахований Податковий розрахунок.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати Податковий розрахунок до ДПС')

    def kep_prepare_signing(self):
        spec = super().kep_prepare_signing()
        for key, data, filename in self._attachment_files():
            doc = dict(spec['documents'][0])
            doc.update(name=key, data_b64=data.decode() if isinstance(data, bytes) else data,
                       filename=filename)
            spec['documents'].append(doc)
        return spec

    def kep_submit_signed(self, signed, auth_signature=None):
        """Головна форма з додатками — одним запитом: кабінет приймає масив звітів."""
        self.ensure_one()
        attachments = self._attachment_files()
        if not attachments:
            return super().kep_submit_signed(signed, auth_signature)
        self._dps_check_can_submit()
        config = self._dps_config()
        missing = [key.upper() for key, _d, _f in attachments if not signed.get(key)]
        if not signed.get('doc') or missing:
            raise UserError(_('Не отримано підпис розрахунку або додатків: %s')
                            % ', '.join(missing or [_('головна форма')]))
        result = config._api_submit_document_presigned(
            signed['doc'], self._dps_filename(), auth_signature,
            extra_files=[(signed[key], filename) for key, _d, filename in attachments])
        self._dps_check_result(result)
        receipt = self._dps_receipt_text(result)
        self._dps_store_receipts(result)
        self._dps_on_submitted(receipt)
        return {'receipt': receipt}

    def _dps_on_submitted(self, receipt):
        self.write({'state': 'submitted', 'submission_date': fields.Date.context_today(self)})
        if self.d5_report_id:
            self.d5_report_id.sudo()._dps_on_submitted(receipt)
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))


class L10nUaPayrollTaxReportD4Line(models.Model):
    _name = 'l10n_ua.payroll.tax.report.d4.line'
    _description = 'Податковий розрахунок: рядок Д4 (4ДФ)'
    _order = 'report_id, rnokpp, income_code'

    report_id = fields.Many2one(
        'l10n_ua.payroll.tax.report', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='report_id.company_id', store=True)
    currency_id = fields.Many2one(related='report_id.currency_id')
    employee_id = fields.Many2one('hr.employee', string='Працівник')
    rnokpp = fields.Char(string='РНОКПП', required=True)
    income_code = fields.Char(string='Ознака доходу', default='101',
                              help='101 — заробітна плата, 102 — винагорода за ЦПХ.')
    income_accrued = fields.Monetary(string='Дохід нарахований')
    income_paid = fields.Monetary(string='Дохід виплачений')
    pdfo_accrued = fields.Monetary(string='ПДФО нарахований')
    pdfo_paid = fields.Monetary(string='ПДФО перерахований')
    mil_accrued = fields.Monetary(string='ВЗ нарахований')
    mil_paid = fields.Monetary(string='ВЗ перерахований')
    date_hire = fields.Date(string='Дата прийняття')
    date_term = fields.Date(string='Дата звільнення')
