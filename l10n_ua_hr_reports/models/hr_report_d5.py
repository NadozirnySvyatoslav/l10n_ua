import base64
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Додаток Д1 «Відомості про нарахування заробітної плати (доходу, грошового
# забезпечення) застрахованим особам» до Податкового розрахунку ЮО — форма
# J0510111, версія 11 (наказ Мінфіну № 4 від 13.01.2015 у ред. наказу № 243
# від 07.05.2026, чинна з 17.07.2026). Коди — fixed-значення офіційного XSD
# ДПС (СКЗ 1.34.9.0), валідація — tests/test_d5_xsd.py.
#
# До версії 11 тут стояла J0510210 — це Д2 (особи, що доглядають за дитиною
# до трьох років), а не Д1: ЄСВ працівників ішов у чужу форму (#210).
D1_C_DOC = 'J05'
D1_C_DOC_SUB = '101'
D1_C_DOC_VER = '11'
D1_SOFTWARE = 'Odoo l10n_ua'

# Категорія працівника (модель) -> код категорії застрахованої особи (гр.8,
# DGI2inom 1..99) за довідником ДПС. Best-effort для домінантних випадків;
# рідкісні категорії уточнюються за фактичним статусом ЗО.
D1_ZO_CATEGORY = {
    '1': 1,   # найманий працівник
    '2': 26,  # особа за ЦПХ-договором
    '3': 2,   # найманий працівник з інвалідністю
    '4': 1,   # декрет — базова категорія (уточнюється за випадком)
}


# Графа 06 «Жінка (Ж), чоловік (Ч)» в електронній формі — ознака 0/1
# (DGOzn). Порядок заповнення відповідності не наводить; прийнято
# 1 — чоловік, 0 — жінка. Звірити з квитанцією першого живого подання.
D1_GENDER_CODE = {'male': 1, 'female': 0}


class HrReportD5(models.Model):
    _name = 'hr.report.d5'
    _description = 'D5 ESV Report'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'year desc, month desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year,
        tracking=True
    )
    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True, tracking=True)
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    
    line_ids = fields.One2many(
        'hr.report.d5.line',
        'report_id',
        string='Report Lines (D1)'
    )
    
    total_employees = fields.Integer(
        string='Total Employees',
        compute='_compute_totals',
        store=True
    )
    total_esv_base = fields.Float(
        string='Total ESV Base',
        compute='_compute_totals',
        store=True
    )
    total_esv = fields.Float(
        string='Total ESV',
        compute='_compute_totals',
        store=True
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('submitted', 'Submitted'),
    ], string='Status', default='draft', tracking=True)
    
    submission_date = fields.Date(string='Submission Date')
    notes = fields.Text(string='Notes')

    xml_file = fields.Binary(string='XML-файл', attachment=True, copy=False)
    xml_filename = fields.Char(copy=False)

    @api.depends('year', 'month')
    def _compute_name(self):
        month_names = dict(self._fields['month'].selection)
        for rec in self:
            rec.name = f'Д5 {month_names.get(rec.month, "")} {rec.year}'

    @api.depends('line_ids.esv_base', 'line_ids.esv_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_employees = len(rec.line_ids)
            rec.total_esv_base = sum(rec.line_ids.mapped('esv_base'))
            rec.total_esv = sum(rec.line_ids.mapped('esv_amount'))

    def action_generate(self):
        """Generate report lines from payslips"""
        self.ensure_one()
        self.line_ids.unlink()
        
        month = int(self.month)
        date_from = fields.Date.from_string(f'{self.year}-{month:02d}-01')
        
        if month == 12:
            date_to = fields.Date.from_string(f'{self.year + 1}-01-01')
        else:
            date_to = fields.Date.from_string(f'{self.year}-{month + 1:02d}-01')
        
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', date_from),
            ('date_to', '<', date_to),
            ('state', '=', 'done'),
        ])
        
        for slip in payslips:
            employee = slip.employee_id
            version = slip.version_id

            # Determine category based on contract type and benefits
            category = '1'  # Default: Employee
            if version:
                if version.contract_type_ua == 'civil':
                    category = '2'  # Civil Contract
                elif version.contract_type_ua == 'gig':
                    category = '2'  # Gig contract treated as civil

            # Check for disability benefits
            if employee.benefit_ids:
                disability_benefits = employee.benefit_ids.filtered(
                    lambda b: 'disability' in b.code.lower() or 'інвалід' in b.name.lower()
                )
                if disability_benefits:
                    category = '3'  # Disabled

            gross = slip.gross_salary or 0.0
            esv_base = slip.esv_base or 0.0
            # Гр. 18 — доплата бази до мінімальної зарплати: частина бази ЄСВ
            # понад фактичний дохід. Коли дохід вищий за максимум, база менша
            # за дохід і доплати немає.
            min_wage_diff = max(0.0, esv_base - gross)
            country = employee.country_id
            self.env['hr.report.d5.line'].create({
                'report_id': self.id,
                'employee_id': employee.id,
                'citizen_ua': not country or country.code == 'UA',
                'gender': employee.gender if employee.gender in ('male', 'female') else False,
                'gross_amount': gross,
                'min_wage_diff': min_wage_diff,
                'employment_days': self._employment_days(
                    version, date_from, date_to),
                'main_job': not version or getattr(
                    version, 'employment_type_ua', 'primary') == 'primary',
                'part_time': bool(version) and 0 < (getattr(
                    version, 'work_rate', 1.0) or 1.0) < 1.0,
                'rnokpp': employee.rnokpp or '',
                'last_name': employee.name.split()[0] if employee.name else '',
                'first_name': employee.name.split()[1] if employee.name and len(employee.name.split()) > 1 else '',
                'middle_name': employee.name.split()[2] if employee.name and len(employee.name.split()) > 2 else '',
                'category': category,
                'start_date': version.contract_date_start if version else None,
                'end_date': version.contract_date_end if version else None,
                'esv_base': slip.esv_base,
                'esv_amount': slip.esv_amount,
                'worked_days': slip.worked_days,
                'worked_hours': slip.worked_hours,
            })
        
        self.write({'state': 'generated'})
        return True

    @api.model
    def _employment_days(self, version, date_from, date_to):
        """Гр. 14: календарні дні трудових відносин у звітному місяці.

        ``date_to`` — перший день наступного місяця (як у пошуку листів).
        """
        start, end = date_from, date_to - timedelta(days=1)
        if version:
            if version.contract_date_start and version.contract_date_start > start:
                start = version.contract_date_start
            if version.contract_date_end and version.contract_date_end < end:
                end = version.contract_date_end
        return max(0, (end - start).days + 1)

    def action_submit(self):
        """Д1 окремо не подається — лише в пакеті Податкового розрахунку ЮО.

        ДПС приймає Д1 як додаток до головної форми J0500111 (LINKED_DOCS);
        самостійний файл кабінет відхиляє. Подання — з документа
        «Податковий розрахунок» (#210), тут лише формування XML.
        """
        raise UserError(_(
            'Додаток Д1 подається лише у складі Податкового розрахунку ЮО '
            '(головна форма J0500111). Сформуйте XML кнопкою «Export XML»; '
            'подання пакетом — з документа «Податковий розрахунок».'))

    # --- контракт l10n_ua.dps.submit.mixin ---

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_('Спочатку згенеруйте звіт (кнопка «Generate»).'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_export_xml()

    def _dps_submit_label(self):
        return _('Подати Д5 (ЄСВ) до ДПС')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'submitted',
            'submission_date': fields.Date.today(),
        })
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_export_xml(self):
        """Сформувати XML Додатка Д1 (J0510111 v11), валідний за XSD ДПС.

        Зберігає результат у ``xml_file`` (кодування windows-1251, як приймає
        ДПС) і публікує повідомлення в чатер. Структуру звірено з офіційним
        XSD (tests/test_xsd_validation.py). Порожня заглушка більше не
        використовується — кнопка справді генерує подавальний файл.
        """
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_('Спочатку згенеруйте звіт (кнопка «Generate»).'))
        xml = self._render_d1_xml(self._d1_vals())
        self.xml_file = base64.b64encode(xml.encode('windows-1251'))
        self.xml_filename = 'J0510111_%s_%02d.xml' % (self.year, int(self.month))
        self.message_post(body=_('Сформовано XML Додатка Д1: %s') % self.xml_filename)
        return True

    def _d1_vals(self):
        """Зібрати значення Додатка 1 із запису (компанія + рядки).

        Обов'язкові реквізити, яких нема в даних, — явна помилка користувачу
        (не підставляємо фейк у документ, який піде до ДПС/ПФУ).
        """
        self.ensure_one()
        company = self.company_id
        edrpou = re.sub(r'\D', '', company.edrpou or '')
        office = company.tax_office_code or ''
        director = company.director_id
        director_rnokpp = re.sub(
            r'\D', '', (director.rnokpp or '') if director else '')
        accountant = company.accountant_id
        accountant_rnokpp = re.sub(
            r'\D', '', (accountant.rnokpp or '') if accountant else '')

        missing = []
        if not edrpou:
            missing.append(_('код ЄДРПОУ компанії'))
        if not office:
            missing.append(_('код ДПІ компанії (tax_office_code)'))
        if not director_rnokpp:
            missing.append(_('РНОКПП керівника (director_id)'))
        if not (director and director.name):
            missing.append(_('ПІБ керівника (director_id)'))
        if missing:
            raise UserError(_(
                'Для формування Додатка 1 заповніть: %s.') % ', '.join(missing))

        month = int(self.month)
        persons = []
        for line in self.line_ids:
            persons.append({
                'rnokpp': re.sub(r'\D', '', line.rnokpp or ''),
                'last_name': line.last_name or '',
                'first_name': line.first_name or '',
                'middle_name': line.middle_name or '',
                'zo_category': D1_ZO_CATEGORY.get(line.category or '1', 1),
                'citizen': 1 if line.citizen_ua else 0,
                'gender': D1_GENDER_CODE.get(line.gender),
                'sick_days': line.sick_days or None,
                'unpaid_days': line.unpaid_days or None,
                'employment_days': line.employment_days,
                'maternity_days': line.maternity_days or None,
                'gross': line.gross_amount or line.esv_base,
                'esv_base': line.esv_base - (line.min_wage_diff or 0.0),
                'min_wage_diff': line.min_wage_diff or None,
                'esv_withheld': 0.0,
                'esv_amount': line.esv_amount,
                'main_job': 1 if line.main_job else 0,
                'part_time': 1 if line.part_time else 0,
                'special_stage': 0,
                'new_workplace': 0,
                'unfixed_hours': 0,
            })
        return {
            'tin': edrpou,
            'c_reg': int(office[:2]) if len(office) >= 2 else 0,
            'c_raj': int(office[2:4]) if len(office) >= 4 else 0,
            'period_month': month,
            'period_type': 1,  # місячна (модель Д5 — помісячна)
            'period_year': self.year,
            'c_sti_orig': office,
            'hzy': self.year,
            'hzm': month,
            'hname': company._l10n_ua_dps_name(),
            'htin': edrpou,
            'hfill': date.today().strftime('%d%m%Y'),
            'hkbos': director_rnokpp,
            'hbos': director.name or '',
            'hkbuh': accountant_rnokpp,
            'hbuh': (accountant.name or '') if accountant else '',
            'persons': persons,
        }

    @api.model
    def _render_d1_xml(self, vals):
        """Рендер XML Додатка Д1 (J0510111 v11) з dict значень.

        Стейтлес (лише ``vals``) — щоб валідацію проти офіційного XSD можна
        було проганяти без записів. Графи таблиці (column-major, ROWNUM — номер
        запису): 05 громадянин України, 06 стать, 07 РНОКПП, 08 категорія ЗО,
        09 код типу нарахувань (лише у випадках 1–15), 10 місяць/рік,
        11 ПІБ, 12 дні непрацездатності, 13 дні без збереження зарплати,
        14 дні трудових відносин, 15 дні відпустки по вагітності й пологах,
        16 нараховано всього, 17 у межах максимуму, 18 доплата до мінімальної,
        19 утриманий ЄСВ, 20 нарахований ЄСВ, 21 основне місце роботи,
        22 неповний робочий час, 23 спецстаж, 24 нове робоче місце,
        26 нефіксований робочий час. Гр. 25 — лише для «Звітного нового» й
        «Уточнюючого», тут не заповнюється.
        """
        def esc(v):
            return escape(str(v or ''))

        def num(v):
            return '%.2f' % (v or 0.0)

        def i(v):  # цілі колонки — 0 має рендеритись як «0»
            return str(int(v))

        persons = vals.get('persons') or []
        for p in persons:
            p.setdefault('month', vals['hzm'])
            p.setdefault('year', vals['hzy'])

        def column(tag, key, fmt):
            rows = []
            for n, p in enumerate(persons, 1):
                val = p.get(key)
                if val in (None, ''):
                    continue
                rows.append('        <%s ROWNUM="%d">%s</%s>' % (
                    tag, n, fmt(val), tag))
            return '\n'.join(rows)

        cols = [
            column('T1RXXXXG5', 'citizen', i),
            column('T1RXXXXG6', 'gender', i),
            column('T1RXXXXG7S', 'rnokpp', esc),
            column('T1RXXXXG8', 'zo_category', i),
            column('T1RXXXXG9', 'accrual_type', i),
            column('T1RXXXXG101', 'month', i),
            column('T1RXXXXG102', 'year', i),
            column('T1RXXXXG111S', 'last_name', esc),
            column('T1RXXXXG112S', 'first_name', esc),
            column('T1RXXXXG113S', 'middle_name', esc),
            column('T1RXXXXG12', 'sick_days', i),
            column('T1RXXXXG13', 'unpaid_days', i),
            column('T1RXXXXG14', 'employment_days', i),
            column('T1RXXXXG15', 'maternity_days', i),
            column('T1RXXXXG16', 'gross', num),
            column('T1RXXXXG17', 'esv_base', num),
            column('T1RXXXXG18', 'min_wage_diff', num),
            column('T1RXXXXG19', 'esv_withheld', num),
            column('T1RXXXXG20', 'esv_amount', num),
            column('T1RXXXXG21', 'main_job', i),
            column('T1RXXXXG22', 'part_time', i),
            column('T1RXXXXG23', 'special_stage', i),
            column('T1RXXXXG24', 'new_workplace', i),
            column('T1RXXXXG26', 'unfixed_hours', i),
        ]
        table = '\n'.join(c for c in cols if c)

        def total(key):
            return sum(p.get(key) or 0.0 for p in persons)

        totals = '\n'.join(
            '        <R01G%d>%s</R01G%d>' % (g, num(total(key)), g)
            for g, key in ((16, 'gross'), (17, 'esv_base'), (18, 'min_wage_diff'),
                           (19, 'esv_withheld'), (20, 'esv_amount'))
        ) if persons else ''

        accountant = ''
        if vals.get('hkbuh') and vals.get('hbuh'):
            accountant = (
                '        <HKBUH>%s</HKBUH>\n'
                '        <HBUH>%s</HBUH>' % (esc(vals['hkbuh']), esc(vals['hbuh'])))

        parts = [
            '<?xml version="1.0" encoding="windows-1251"?>',
            '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:noNamespaceSchemaLocation="J0510111.xsd">',
            '    <DECLARHEAD>',
            '        <TIN>%s</TIN>' % esc(vals['tin']),
            '        <C_DOC>%s</C_DOC>' % D1_C_DOC,
            '        <C_DOC_SUB>%s</C_DOC_SUB>' % D1_C_DOC_SUB,
            '        <C_DOC_VER>%s</C_DOC_VER>' % D1_C_DOC_VER,
            '        <C_DOC_TYPE>%s</C_DOC_TYPE>' % vals.get('doc_type', 0),
            '        <C_DOC_CNT>%s</C_DOC_CNT>' % vals.get('doc_cnt', 1),
            '        <C_REG>%s</C_REG>' % vals['c_reg'],
            '        <C_RAJ>%s</C_RAJ>' % vals['c_raj'],
            '        <PERIOD_MONTH>%s</PERIOD_MONTH>' % vals['period_month'],
            '        <PERIOD_TYPE>%s</PERIOD_TYPE>' % vals['period_type'],
            '        <PERIOD_YEAR>%s</PERIOD_YEAR>' % vals['period_year'],
            '        <C_STI_ORIG>%s</C_STI_ORIG>' % esc(vals['c_sti_orig']),
            '        <C_DOC_STAN>1</C_DOC_STAN>',
            '        <D_FILL>%s</D_FILL>' % vals['hfill'],
            '        <SOFTWARE>%s</SOFTWARE>' % D1_SOFTWARE,
            '    </DECLARHEAD>',
            '    <DECLARBODY>',
            '        <HZ>1</HZ>',
            '        <HZY>%s</HZY>' % vals['hzy'],
            '        <HZM>%s</HZM>' % vals['hzm'],
            '        <HNAME>%s</HNAME>' % esc(vals['hname']),
            '        <HTIN>%s</HTIN>' % esc(vals['htin']),
        ]
        if table:
            parts.append(table)
        if totals:
            parts.append(totals)
        parts.append('        <HFILL>%s</HFILL>' % vals['hfill'])
        parts.append('        <HKBOS>%s</HKBOS>' % esc(vals['hkbos']))
        parts.append('        <HBOS>%s</HBOS>' % esc(vals['hbos']))
        if accountant:
            parts.append(accountant)
        parts.append('    </DECLARBODY>')
        parts.append('</DECLAR>')
        return '\n'.join(parts)

    _unique_year_month_company_id = models.Constraint(
        'unique(year, month, company_id)',
        'D5 report for this period already exists!',
    )


class HrReportD5Line(models.Model):
    _name = 'hr.report.d5.line'
    _description = 'D5 Report Line (D1 Appendix)'
    _order = 'employee_id'

    report_id = fields.Many2one(
        'hr.report.d5',
        string='Report',
        required=True,
        ondelete='cascade'
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True
    )
    
    rnokpp = fields.Char(string='RNOKPP', required=True)
    last_name = fields.Char(string='Last Name')
    first_name = fields.Char(string='First Name')
    middle_name = fields.Char(string='Middle Name')
    
    category = fields.Selection([
        ('1', '1 - Employee'),
        ('2', '2 - Civil Contract'),
        ('3', '3 - Disabled'),
        ('4', '4 - Maternity'),
    ], string='Category', default='1')
    
    esv_base = fields.Float(string='ESV Base')
    esv_amount = fields.Float(string='ESV Amount')

    # Графи Д1 (J0510111), яких не було в рядку до версії 11.
    citizen_ua = fields.Boolean(string='Citizen of Ukraine', default=True)
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')],
                              string='Gender')
    gross_amount = fields.Float(
        string='Accrued Total',
        help='Д1, гр. 16: загальна сума нарахованої зарплати за місяць.')
    min_wage_diff = fields.Float(
        string='Top-up to Minimum Wage',
        help='Д1, гр. 18: різниця між мінімальною і фактично нарахованою '
             'зарплатою, на яку нараховано ЄСВ.')
    employment_days = fields.Integer(
        string='Employment Days',
        help='Д1, гр. 14: календарні дні трудових відносин у місяці.')
    sick_days = fields.Integer(string='Sick Leave Days', help='Д1, гр. 12.')
    unpaid_days = fields.Integer(string='Unpaid Leave Days', help='Д1, гр. 13.')
    maternity_days = fields.Integer(string='Maternity Leave Days', help='Д1, гр. 15.')
    main_job = fields.Boolean(string='Main Job', default=True, help='Д1, гр. 21.')
    part_time = fields.Boolean(string='Part Time', help='Д1, гр. 22.')
    
    worked_days = fields.Integer(string='Worked Days')
    worked_hours = fields.Float(string='Worked Hours')
    
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    termination_reason = fields.Char(string='Termination Reason')
    
    notes = fields.Char(string='Notes')
