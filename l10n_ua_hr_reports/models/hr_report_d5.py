import base64
import re
from datetime import date
from xml.sax.saxutils import escape

from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Додаток 1 (Відомості про нарахування ЄСВ) об'єднаного розрахунку —
# форма J0510210, версія 10 (Наказ Мінфіну № 4 від 13.01.2015 у ред. № 39
# від 24.04.2025 зі змінами № 53 від 30.05.2025). Коди C_DOC/C_DOC_SUB/
# C_DOC_VER — fixed-значення з офіційного XSD ДПС (пакет СКЗ), звірені
# в tests/test_xsd_validation.py проти J0510210.xsd.
D1_C_DOC = 'J05'
D1_C_DOC_SUB = '102'
D1_C_DOC_VER = '10'
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

            self.env['hr.report.d5.line'].create({
                'report_id': self.id,
                'employee_id': employee.id,
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

    def action_submit(self):
        """Відкрити КЕП-підпис і подання Д5/Додатка 1 (ЄСВ) до ДПС."""
        return self.action_kep_submit()

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
        """Сформувати XML Додатка 1 (ЄСВ, J0510210 v10), валідний за XSD ДПС.

        Зберігає результат у ``xml_file`` (кодування windows-1251, як приймає
        ДПС) і публікує повідомлення в чатер. Структуру звірено з офіційним
        XSD (tests/test_xsd_validation.py). Порожня заглушка більше не
        використовується — кнопка справді генерує подавальний файл.
        """
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_('Спочатку згенеруйте звіт (кнопка «Generate»).'))
        xml = self._render_d1_xml(self._d1_vals())
        self.xml_file = base64.b64encode(xml.encode('windows-1251')).decode()
        self.xml_filename = 'J0510210_%s_%02d.xml' % (self.year, int(self.month))
        self.message_post(body=_('Сформовано XML Додатка 1 (ЄСВ): %s') % self.xml_filename)
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
                'esv_base': line.esv_base,
                'esv_amount': line.esv_amount,
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
            'hname': company.name or '',
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
        """Рендер XML Додатка 1 (J0510210 v10) з dict значень.

        Стейтлес (лише ``vals``) — щоб валідацію проти офіційного XSD можна
        було проганяти без залежності від записів. Порядок і склад елементів
        звірені з J0510210.xsd (DHead: fixed J05/102/10; DBody: choice
        HZ|HZN|HZU, HZY, HZM, HNAME, HTIN, таблиця персон column-major
        T1RXXXXG5..G17, підсумки R01G14..G16, HFILL, HKBOS, HBOS).

        Поколонкова відомість про ставки ЄСВ (R01..R06 G3..G6) — опційний блок
        (minOccurs=0), наразі не заповнюється (потребує розбивки за ставками);
        документ лишається XSD-валідним. Це наступний інкремент.
        """
        def esc(v):
            return escape(str(v or ''))

        def num(v):
            return '%.2f' % (v or 0.0)

        def i(v):  # цілі колонки (ознаки/тип/період) — 0 має рендеритись як «0»
            return str(int(v))

        persons = vals.get('persons') or []

        # Технічні сталі колонки (ознаки/тип нарахування/період) — по кожній
        # особі, до рендеру column-major нижче.
        for p in persons:
            p.setdefault('g5', 0)
            p.setdefault('accrual_type', 1)
            p.setdefault('month', vals['hzm'])
            p.setdefault('year', vals['hzy'])
            p.setdefault('g17', 0)

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
            column('T1RXXXXG5', 'g5', i),
            column('T1RXXXXG6S', 'rnokpp', lambda v: esc(v)),
            column('T1RXXXXG71S', 'last_name', lambda v: esc(v)),
            column('T1RXXXXG72S', 'first_name', lambda v: esc(v)),
            column('T1RXXXXG73S', 'middle_name', lambda v: esc(v)),
            column('T1RXXXXG8', 'zo_category', i),
            column('T1RXXXXG12', 'accrual_type', i),
            column('T1RXXXXG131', 'month', i),
            column('T1RXXXXG132', 'year', i),
            column('T1RXXXXG14', 'esv_base', num),
            column('T1RXXXXG15', 'esv_base', num),
            column('T1RXXXXG16', 'esv_amount', num),
            column('T1RXXXXG17', 'g17', i),
        ]
        table = '\n'.join(c for c in cols if c)

        tot_base = sum(p['esv_base'] for p in persons)
        tot_esv = sum(p['esv_amount'] for p in persons)

        totals = (
            '        <R01G14>%s</R01G14>\n'
            '        <R01G15>%s</R01G15>\n'
            '        <R01G16>%s</R01G16>' % (
                num(tot_base), num(tot_base), num(tot_esv))
        ) if persons else ''

        accountant = ''
        if vals.get('hkbuh') and vals.get('hbuh'):
            accountant = (
                '        <HKBUH>%s</HKBUH>\n'
                '        <HBUH>%s</HBUH>\n' % (
                    esc(vals['hkbuh']), esc(vals['hbuh']))
            )

        parts = [
            '<?xml version="1.0" encoding="windows-1251"?>',
            '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:noNamespaceSchemaLocation="J0510210.xsd">',
            '    <DECLARHEAD>',
            '        <TIN>%s</TIN>' % esc(vals['tin']),
            '        <C_DOC>%s</C_DOC>' % D1_C_DOC,
            '        <C_DOC_SUB>%s</C_DOC_SUB>' % D1_C_DOC_SUB,
            '        <C_DOC_VER>%s</C_DOC_VER>' % D1_C_DOC_VER,
            '        <C_DOC_TYPE>0</C_DOC_TYPE>',
            '        <C_DOC_CNT>1</C_DOC_CNT>',
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
            parts.append(accountant.rstrip('\n'))
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
    
    worked_days = fields.Integer(string='Worked Days')
    worked_hours = fields.Float(string='Worked Hours')
    
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    termination_reason = fields.Char(string='Termination Reason')
    
    notes = fields.Char(string='Notes')
