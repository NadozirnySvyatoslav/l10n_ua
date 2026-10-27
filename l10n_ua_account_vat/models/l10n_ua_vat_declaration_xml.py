"""XML декларації з ПДВ (J0200126), додатків Д1 (J0200526) і Д2 (J0215226) та подання до ДПС.

Форма — наказ Мінфіну № 21 у редакції наказу № 400 від 09.08.2024; структура —
XSD з пакета СКЗ ДПС (``tests/schemas``). Рядки основної форми — у цілих гривнях
(DGdecimal0), таблиці додатка — з копійками (Decimal2Column).

Підтримується типовий місяць платника-юрособи: зобов'язання за ПН/РК, податковий
кредит за ПН/РК з розшифровкою за постачальниками (Д1, таблиці 2.1 і 2.2), імпорт;
видані ПН і РК на збільшення, не зареєстровані в ЄРПН на дату подання (Д1, таблиці
1.1.1/1.1.2 і 1.2.1/1.2.3 — для умовного ІПН нерезидента 500000000000); від'ємне
значення (рядки 19–21 і Д2, таблиця 1) без погашення боргу й бюджетного відшкодування.
Пакет збирається з реєстру додатків (_vat_attachments): Д1 і Д2 — тут, Д3–Д6 і рідкісні
таблиці (Д1 1.3, Д2 1.1/2/3) — в окремих файлах l10n_ua_vat_declaration_d*.py / _rare.py.
РК на зменшення, не зареєстровані в ЄРПН, XML не пропускає.
"""
import base64
import re
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

SOFTWARE = 'Odoo l10n_ua'
FORM_VERSION = '26'
# C_DOC_SUB кожної форми пакета: (юрособа J02, ФОП F02). Д1 ФОП — F0200426.
FORM_SUBS = {
    'main': ('001', '001'), 'd1': ('005', '004'), 'd2': ('152', '152'),
    'd3': ('998', '998'), 'd4': ('993', '993'), 'd5': ('157', '157'), 'd6': ('158', '158'),
}
ATTACHMENT_KEYS = ('d1', 'd2', 'd3', 'd4', 'd5', 'd6')
# Сумісність зі старими посиланнями: форми юрособи.
MAIN_FORM = ('J02', '001', FORM_VERSION)
D1_FORM = ('J02', '005', FORM_VERSION)
D2_FORM = ('J02', '152', FORM_VERSION)
NONRESIDENT_IPN = '500000000000'
# Таблиці розділу I Д1: (префікс, рядок підсумку, кількість граф сум 6..).
D1_SECTION1 = {
    't111': ('T111', 'R0111', 4), 't112': ('T112', 'R0112', 3),
    't121': ('T121', 'R0121', 4), 't123': ('T123', 'R0123', 3),
    't124': ('T124', 'R0124', 4),
}

# Рядки основної форми в порядку XSD: (тег, поле моделі).
MAIN_ROWS = [
    ('R11GA', 'line_1_1_base'), ('R11GB', 'line_1_1_vat'),
    ('R12GA', 'line_1_2_base'), ('R12GB', 'line_1_2_vat'),
    ('R13GA', 'line_1_3_base'), ('R13GB', 'line_1_3_vat'),
    ('R21GA', 'line_2_base'), ('R22GA', 'line_2_2_base'),
    ('R30GA', 'line_3_base'),
    ('R41GA', 'line_4_1_base'), ('R41GB', 'line_4_1_vat'),
    ('R411GA', 'line_4_1_1_base'), ('R411GB', 'line_4_1_1_vat'),
    ('R42GA', 'line_4_2_base'), ('R42GB', 'line_4_2_vat'),
    ('R421GA', 'line_4_2_1_base'), ('R421GB', 'line_4_2_1_vat'),
    ('R43GA', 'line_4_3_base'), ('R43GB', 'line_4_3_vat'),
    ('R431GA', 'line_4_3_1_base'), ('R431GB', 'line_4_3_1_vat'),
    ('R50GA', 'line_5_base'), ('R51GA', 'line_5_1_base'),
    ('R61GA', 'line_6_1_base'), ('R61GB', 'line_6_1_vat'),
    ('R62GA', 'line_6_2_base'), ('R62GB', 'line_6_2_vat'),
    ('R71GA', 'line_7_1_base'), ('R71GB', 'line_7_1_vat'),
    ('R722GA', 'line_7_2_2_base'), ('R722GB', 'line_7_2_2_vat'),
    ('R723GA', 'line_7_2_3_base'), ('R723GB', 'line_7_2_3_vat'),
    ('R90GB', 'line_9_vat'),
    ('R101GA', 'line_10_1_base'), ('R101GB', 'line_10_1_vat'),
    ('R102GA', 'line_10_2_base'), ('R102GB', 'line_10_2_vat'),
    ('R103GA', 'line_10_3_base'), ('R103GB', 'line_10_3_vat'),
    ('R104GA', 'line_10_4_base'),
    ('R111GA', 'line_11_1_base'), ('R111GB', 'line_11_1_vat'),
    ('R112GA', 'line_11_2_base'), ('R112GB', 'line_11_2_vat'),
    ('R113GA', 'line_11_3_base'), ('R113GB', 'line_11_3_vat'),
    ('R114GA', 'line_11_4_base'),
    ('R131GA', 'line_13_1_base'), ('R131GB', 'line_13_1_vat'),
    ('R132GA', 'line_13_2_base'), ('R132GB', 'line_13_2_vat'),
    ('R140GB', 'line_14_vat'),
    ('R150GB', 'line_15_vat'),
    ('R160GB', 'line_16_1_vat'), ('R161GB', 'line_16_1_vat'),
    ('R170GB', 'line_17_vat'),
    ('R180GB', 'line_18_vat'),
    ('R190GB', 'line_19_vat'),
    ('R191GB', 'line_19_1_vat'),
    ('R200GB', 'line_20_vat'),
    ('R201GB', 'line_20_1_vat'),
    ('R202GB', 'line_20_2_vat'),
    ('R2021GB', 'line_20_2_1_vat'),
    ('R2022GB', 'line_20_2_2_vat'),
    ('R203GB', 'line_20_3_vat'),
    ('R210GB', 'line_21_vat'),
]


def _int(value):
    """Сума для DGdecimal0: цілі гривні."""
    return '%d' % float_round(value or 0.0, precision_digits=0)


def _dec2(value):
    return '%.2f' % float_round(value or 0.0, precision_digits=2)


def _filename(head):
    """Ім'я файлу за наказом № 729 — з тих самих реквізитів, що й DECLARHEAD."""
    return '%s%s%s%s%s%s%s%s%s%s%s%s%s.xml' % (
        head['c_reg'], head['c_raj'], head['tin'].zfill(10),
        head['c_doc'], head['c_doc_sub'], head['c_doc_ver'].zfill(2),
        head['c_doc_stan'], str(head['c_doc_type']).zfill(2), str(head['c_doc_cnt']).zfill(7),
        head['period_type'], str(head['period_month']).zfill(2), head['period_year'],
        head['c_sti_orig'])


class L10nUaVatDeclarationXml(models.Model):
    _name = 'l10n_ua.vat.declaration'
    _inherit = ['l10n_ua.vat.declaration', 'l10n_ua.dps.submit.mixin']

    xml_file = fields.Binary(string='XML декларації', attachment=True, copy=False)
    xml_filename = fields.Char(string='Ім\'я файлу декларації', copy=False)
    d1_xml_file = fields.Binary(string='XML додатка Д1', attachment=True, copy=False)
    d1_xml_filename = fields.Char(string='Ім\'я файлу Д1', copy=False)
    d2_xml_file = fields.Binary(string='XML додатка Д2', attachment=True, copy=False)
    d2_xml_filename = fields.Char(string='Ім\'я файлу Д2', copy=False)
    d3_xml_file = fields.Binary(string='XML додатка Д3', attachment=True, copy=False)
    d3_xml_filename = fields.Char(string='Ім\'я файлу Д3', copy=False)
    d4_xml_file = fields.Binary(string='XML додатка Д4', attachment=True, copy=False)
    d4_xml_filename = fields.Char(string='Ім\'я файлу Д4', copy=False)
    d5_xml_file = fields.Binary(string='XML додатка Д5', attachment=True, copy=False)
    d5_xml_filename = fields.Char(string='Ім\'я файлу Д5', copy=False)
    d6_xml_file = fields.Binary(string='XML додатка Д6', attachment=True, copy=False)
    d6_xml_filename = fields.Char(string='Ім\'я файлу Д6', copy=False)
    submission_date = fields.Date(string='Дата подання', copy=False)
    signatory_name = fields.Char(
        string='Керівник',
        compute='_compute_signatory', store=True, readonly=False,
        help='Власне ім\'я ПРІЗВИЩЕ керівника (уповноваженої особи) для підпису декларації',
    )
    signatory_rnokpp = fields.Char(
        string='РНОКПП керівника',
        compute='_compute_signatory', store=True, readonly=False,
    )
    accountant_name = fields.Char(string='Головний бухгалтер')
    accountant_rnokpp = fields.Char(string='РНОКПП головного бухгалтера')

    @api.depends('company_id')
    def _compute_signatory(self):
        """Керівник — з картки компанії, якщо встановлено кадровий модуль (director_id)."""
        for rec in self:
            director = (rec.company_id.director_id
                        if 'director_id' in rec.company_id._fields else False)
            if director and not rec.signatory_name:
                rec.signatory_name = director.name
                rec.signatory_rnokpp = getattr(director, 'rnokpp', False) or False

    # ------------------------------------------------------------------ дані

    def _is_fop_declaration(self):
        return bool(self.company_id.l10n_ua_is_fop)

    def _vat_form(self, key):
        """(C_DOC, C_DOC_SUB, C_DOC_VER) форми пакета: J02 — юрособа, F02 — ФОП."""
        fop = self._is_fop_declaration()
        return ('F02' if fop else 'J02', FORM_SUBS[key][1 if fop else 0], FORM_VERSION)

    def _vat_tin(self):
        """HTIN/TIN: ЄДРПОУ юрособи або РНОКПП ФОП."""
        company = self.company_id
        if self._is_fop_declaration():
            return re.sub(r'\D', '', company.vat or company.company_registry or '')
        return re.sub(r'\D', '', company.edrpou or company.company_registry or '')

    def _vat_head(self, form, linked=None):
        """Реквізити DECLARHEAD; ``linked`` — список (форма, ім'я файлу, TYPE) пов'язаних."""
        self.ensure_one()
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        office_code = re.sub(r'\D', '', (office.code if office else '')
                             or company.tax_office_code or '')
        period = self.period_id
        return {
            'tin': self._vat_tin(),
            'c_doc': form[0], 'c_doc_sub': form[1], 'c_doc_ver': form[2],
            'c_doc_type': 0, 'c_doc_cnt': 1, 'c_doc_stan': '1',
            'c_reg': office_code[:2], 'c_raj': office_code[2:4],
            'period_month': period.date_end.month, 'period_type': '1',
            'period_year': period.date_end.year, 'c_sti_orig': office_code,
            'office_name': office.name if office else '',
            'linked': linked or [],
        }

    def _check_vat_xml_ready(self):
        """Помилки до формування — усе, чого бракує, одним повідомленням."""
        self.ensure_one()
        problems = self._vat_xml_problems()
        if problems:
            raise UserError(_('Неможливо сформувати XML декларації з ПДВ:\n• %s')
                            % '\n• '.join(problems))

    def _vat_xml_problems(self):
        """Список проблем; додатки дописують свої через super()."""
        self.ensure_one()
        company = self.company_id
        problems = []
        period = self.period_id
        if not period.date_start or not period.date_end or \
                period.date_start.month != period.date_end.month:
            # Податковий період з ПДВ — календарний місяць (ст. 202 ПКУ); форма
            # № 400 не має квартальних полів.
            problems.append(_('декларація з ПДВ подається лише за календарний місяць'))
        tin = self._vat_tin()
        if self._is_fop_declaration():
            if not re.fullmatch(r'\d{10}', tin):
                problems.append(_('РНОКПП ФОП (10 цифр, поле «ІПН/РНОКПП» компанії)'))
        elif not tin:
            problems.append(_('код ЄДРПОУ компанії'))
        if not re.fullmatch(r'\d{12}', company.l10n_ua_vat_ipn or ''):
            problems.append(_('ІПН платника ПДВ компанії (12 цифр)'))
        office = company.l10n_ua_tax_office_id
        if not re.fullmatch(r'\d{4}', re.sub(r'\D', '', (office.code if office else '')
                                              or company.tax_office_code or '')):
            problems.append(_('податкова інспекція компанії (4-значний код ДПІ)'))
        if not self.signatory_name or not re.fullmatch(r'\d{10}', self.signatory_rnokpp or ''):
            problems.append(_('керівник і його РНОКПП (вкладка «Подання»)'))
        decreasing = self._d1_unregistered_lines().filtered(
            lambda l: l.doc_type == 'rk' and l.vat_amount < 0)
        if decreasing:
            problems.append(_(
                'РК на зменшення не зареєстровані в ЄРПН (%s) — без реєстрації вони не '
                'зменшують зобов\'язання; зареєструйте їх або приберіть з реєстру')
                % ', '.join(decreasing.tax_invoice_id.mapped('display_name')[:5]))
        no_buyer_ipn = self._d1_unregistered_lines().filtered(
            lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or ''))
        if no_buyer_ipn:
            problems.append(_('ІПН покупців у незареєстрованих ПН/РК: %s')
                            % ', '.join(no_buyer_ipn.mapped(
                                lambda l: l.partner_id.display_name or l.invoice_number
                                or '?')[:5]))
        problems += self._d2_check()
        if (self.line_20_1_vat or 0.0) < 0 or (self.line_20_2_1_vat or 0.0) < 0 \
                or (self.line_20_2_2_vat or 0.0) < 0:
            problems.append(_('рядки 20.1, 20.2.1, 20.2.2 не можуть бути від\'ємними'))
        if float_compare((self.line_20_1_vat or 0.0) + (self.line_20_2_vat or 0.0),
                         self.line_20_vat or 0.0, precision_digits=0) > 0:
            problems.append(_('рядки 20.1 + 20.2 перевищують рядок 20 (від\'ємне значення '
                              'в межах Σнакл)'))
        no_ipn = self._d1_lines().filtered(
            lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or ''))
        if no_ipn:
            problems.append(_('ІПН постачальників: %s')
                            % ', '.join(no_ipn.partner_id.mapped('display_name')[:5]))
        return problems

    def _d1_lines(self):
        """Рядки реєстру отриманих, що розшифровуються в Д1 (без імпорту)."""
        return self.register_received_id.line_ids.filtered(
            lambda l: not l.tax_invoice_id.is_import)

    def _d1_unregistered_lines(self):
        """Видані ПН/РК, не зареєстровані в ЄРПН на дату подання (Д1, розділ I)."""
        return self.register_issued_id.line_ids.filtered(
            lambda l: l.tax_invoice_id and l.tax_invoice_id.state != 'registered')

    def _d1_section1(self):
        """Таблиці 1.1.1/1.1.2 (ПН) і 1.2.1/1.2.3 (РК на збільшення) — по документу.

        Рядок: (ІПН, дата, номер, [обсяг, ПДВ 20 %, ПДВ 7 %(, ПДВ 14 %)], ознака «+»).
        РК річного перерахунку частки (п. 199.4) — таблиця 1.2.4.
        """
        self.ensure_one()
        tables = {key: [] for key in D1_SECTION1}
        for line in self._d1_unregistered_lines().sorted(lambda l: (l.date, l.id)):
            nonresident = line.partner_ipn == NONRESIDENT_IPN
            invoice = line.tax_invoice_id
            if line.doc_type == 'rk':
                key = 't124' if invoice.vat_199_recalc else ('t123' if nonresident else 't121')
            else:
                key = 't112' if nonresident else 't111'
            special = bool(invoice.vat_special_basis
                           or invoice.original_invoice_id.vat_special_basis)
            amounts = [line.base_20 + line.base_7 + line.base_14, line.vat_20, line.vat_7,
                       line.vat_14][:D1_SECTION1[key][2]]
            tables[key].append((line.partner_ipn, line.invoice_date or invoice.date or line.date,
                                line.invoice_number or invoice.number or invoice.name or '',
                                amounts, special))
        return tables

    def _d1_tables(self):
        """Таблиці 2.1 (ПН) і 2.2 (РК) додатка Д1, згруповані за постачальником і періодом."""
        self.ensure_one()
        t21 = defaultdict(lambda: [0.0] * 4)
        t22 = defaultdict(lambda: [0.0] * 4)
        for line in self._d1_lines():
            amounts = (line.base_20 + line.base_7 + line.base_14, line.vat_20, line.vat_7,
                       line.vat_14)
            if line.doc_type == 'rk':
                original = line.tax_invoice_id.original_invoice_id.date or line.date
                key = (line.partner_ipn, original.month, original.year,
                       line.date.month, line.date.year)
                target = t22[key]
            else:
                key = (line.partner_ipn, line.date.month, line.date.year)
                target = t21[key]
            for i, value in enumerate(amounts):
                target[i] += value
        return sorted(t21.items()), sorted(t22.items())

    # ------------------------------------------------------------------ XML

    def _vat_attachments(self):
        """Додатки, потрібні цій декларації: [(ключ, render(head) -> bytes)].

        Порядок — як у пакеті ДПС. Модулі/файли з іншими додатками дописують свої
        через super().
        """
        self.ensure_one()
        result = []
        t21, t22 = self._d1_tables()
        section1 = self._d1_section1()
        if t21 or t22 or any(section1.values()) or self._d1_has_extra():
            result.append(('d1', lambda head: self._render_d1(head, t21, t22, section1)))
        if float_round(self.line_19_vat, precision_digits=0) > 0 or self._d2_has_extra():
            result.append(('d2', self._render_d2))
        return result

    def action_generate_xml(self):
        for rec in self:
            rec._check_vat_xml_ready()
            main_head = rec._vat_head(rec._vat_form('main'))
            main_name = _filename(main_head)
            vals = {}
            for key in ATTACHMENT_KEYS:
                vals.update({f'{key}_xml_file': False, f'{key}_xml_filename': False})
            attachments = sorted(rec._vat_attachments(), key=lambda a: ATTACHMENT_KEYS.index(a[0]))
            for key, render in attachments:
                form = rec._vat_form(key)
                head = rec._vat_head(form, linked=[(rec._vat_form('main'), main_name, 2)])
                main_head['linked'].append((form, _filename(head), 1))
                xml = render(head)
                vals.update({f'{key}_xml_file': base64.b64encode(xml),
                             f'{key}_xml_filename': dps_standard_filename(xml)})
            main_xml = rec._render_main(main_head, keys={key for key, _r in attachments})
            vals.update(xml_file=base64.b64encode(main_xml),
                        xml_filename=dps_standard_filename(main_xml))
            rec.write(vals)
        return True

    def _render_head(self, head):
        linked = head['linked']
        if linked:
            linked_xml = '<LINKED_DOCS>%s</LINKED_DOCS>' % ''.join(
                '<DOC NUM="%s" TYPE="%s"><C_DOC>%s</C_DOC><C_DOC_SUB>%s</C_DOC_SUB>'
                '<C_DOC_VER>%s</C_DOC_VER><C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>1</C_DOC_CNT>'
                '<C_DOC_STAN>1</C_DOC_STAN><FILENAME>%s</FILENAME></DOC>'
                % (num, link_type, form[0], form[1], form[2], fname[:-4] + '.XML')
                for num, (form, fname, link_type) in enumerate(linked, 1))
        else:
            linked_xml = '<LINKED_DOCS xsi:nil="true"/>'
        return (
            '<DECLARHEAD>'
            f'<TIN>{head["tin"]}</TIN><C_DOC>{head["c_doc"]}</C_DOC>'
            f'<C_DOC_SUB>{head["c_doc_sub"]}</C_DOC_SUB><C_DOC_VER>{head["c_doc_ver"]}</C_DOC_VER>'
            f'<C_DOC_TYPE>{head["c_doc_type"]}</C_DOC_TYPE><C_DOC_CNT>{head["c_doc_cnt"]}</C_DOC_CNT>'
            f'<C_REG>{head["c_reg"]}</C_REG><C_RAJ>{head["c_raj"]}</C_RAJ>'
            f'<PERIOD_MONTH>{head["period_month"]}</PERIOD_MONTH>'
            f'<PERIOD_TYPE>{head["period_type"]}</PERIOD_TYPE>'
            f'<PERIOD_YEAR>{head["period_year"]}</PERIOD_YEAR>'
            f'<C_STI_ORIG>{head["c_sti_orig"]}</C_STI_ORIG>'
            f'<C_DOC_STAN>{head["c_doc_stan"]}</C_DOC_STAN>{linked_xml}'
            f'<D_FILL>{date.today():%d%m%Y}</D_FILL><SOFTWARE>{SOFTWARE}</SOFTWARE>'
            '</DECLARHEAD>')

    def _render_signers(self):
        xml = '<HFILL>%s</HFILL><HBOS>%s</HBOS><HKBOS>%s</HKBOS>' % (
            date.today().strftime('%d%m%Y'), escape(self.signatory_name or ''),
            self.signatory_rnokpp or '')
        if self.accountant_name and self.accountant_rnokpp:
            xml += '<HBUH>%s</HBUH><HKBUH>%s</HKBUH>' % (
                escape(self.accountant_name), self.accountant_rnokpp)
        return xml

    def _render_taxpayer(self, head):
        company = self.company_id
        return (f'<HZ>1</HZ><HZY>{head["period_year"]}</HZY><HZM>{head["period_month"]}</HZM>'
                f'<HNAME>{escape(company._l10n_ua_dps_name())}</HNAME>'
                f'<HTIN>{head["tin"]}</HTIN><HNPDV>{company.l10n_ua_vat_ipn}</HNPDV>')

    @staticmethod
    def _wrap(form, head_xml, body_xml):
        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               f'xsi:noNamespaceSchemaLocation="{"".join(form)}.xsd">'
               f'{head_xml}<DECLARBODY>{body_xml}</DECLARBODY></DECLAR>')
        return xml.encode('windows-1251', errors='xmlcharrefreplace')

    def _render_main(self, head, keys=()):
        self.ensure_one()
        company = self.company_id
        address = ', '.join(filter(None, [company.zip, company.state_id.name, company.city,
                                          company.street, company.street2]))
        body = [self._render_taxpayer(head), f'<HLOC>{escape(address)}</HLOC>']
        if company.zip:
            body.append(f'<HZIP>{escape(company.zip)}</HZIP>')
        body.append(f'<HSTI>{escape(head["office_name"])}</HSTI>')
        for tag, field in MAIN_ROWS:
            if tag == 'R191GB' and 'd2' in keys:
                # Службове поле рядка 19.1: сума за п. 200-1.3 на дату подання.
                body.append(f'<R191G3>{_int(self.vat_limit_amount)}</R191G3>')
            value = self[field]
            if float_round(value or 0.0, precision_digits=0):
                body.append(f'<{tag}>{_int(value)}</{tag}>')
        for key in ATTACHMENT_KEYS:
            if key in keys:
                body.append(f'<HD{key[1]}>1</HD{key[1]}>')
        body.append(self._render_signers())
        return self._wrap(self._vat_form('main'), self._render_head(head), ''.join(body))

    def _render_d1(self, head, t21, t22, section1=None):
        """Д1: таблиці розділу I і 2.1/2.2 — стовпцями з ROWNUM, як вимагає XSD."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]

        def column(prefix, col, rows, fmt):
            return ''.join(f'<{prefix}RXXXXG{col} ROWNUM="{n}">{fmt(row)}</{prefix}RXXXXG{col}>'
                           for n, row in enumerate(rows, 1))

        for key, (prefix, total, ncols) in D1_SECTION1.items():
            rows = (section1 or {}).get(key)
            if not rows:
                continue
            body += [
                column(prefix, '2', rows, lambda r: r[0]),
                column(prefix, '3D', rows, lambda r: r[1].strftime('%d%m%Y')),
                column(prefix, '4S', rows, lambda r: escape(r[2])),
                ''.join(f'<{prefix}RXXXXG5 ROWNUM="{n}">1</{prefix}RXXXXG5>'
                        for n, r in enumerate(rows, 1) if r[4]),
            ]
            for i in range(ncols):
                body.append(column(prefix, str(6 + i), rows, lambda r, i=i: _dec2(r[3][i])))
            for i in range(ncols):
                body.append(f'<{total}G{6 + i}>{_int(sum(r[3][i] for r in rows))}</{total}G{6 + i}>')
        body.append(self._render_d1_extra())

        if t21:
            rows = [(key, [*amounts, sum(amounts[1:])]) for key, amounts in t21]
            body += [
                column('T21', '2', rows, lambda r: r[0][0]),
                column('T21', '31', rows, lambda r: r[0][1]),
                column('T21', '32', rows, lambda r: r[0][2]),
            ]
            for col, idx in (('6', 0), ('7', 1), ('8', 2), ('9', 3), ('10', 4)):
                body.append(column('T21', col, rows, lambda r, i=idx: _dec2(r[1][i])))
            for col, idx in (('6', 0), ('7', 1), ('8', 2), ('9', 3), ('10', 4)):
                body.append(f'<R021G{col}>{_int(sum(r[1][idx] for r in rows))}</R021G{col}>')
        if t22:
            rows = [(key, [*amounts, sum(amounts[1:])]) for key, amounts in t22]
            body += [
                column('T22', '2', rows, lambda r: r[0][0]),
                column('T22', '311', rows, lambda r: r[0][1]),
                column('T22', '312', rows, lambda r: r[0][2]),
                column('T22', '331', rows, lambda r: r[0][3]),
                column('T22', '332', rows, lambda r: r[0][4]),
            ]
            for col, idx in (('4', 0), ('5', 1), ('6', 2), ('7', 3), ('8', 4)):
                body.append(column('T22', col, rows, lambda r, i=idx: _dec2(r[1][i])))
            for col, idx in (('4', 0), ('5', 1), ('6', 2), ('7', 3), ('8', 4)):
                body.append(f'<R022G{col}>{_int(sum(r[1][idx] for r in rows))}</R022G{col}>')
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d1'), self._render_head(head), ''.join(body))

    def _d1_has_extra(self):
        """Додаткові таблиці Д1 (1.3) — див. l10n_ua_vat_declaration_rare."""
        return False

    def _d2_has_extra(self):
        """Додаткові таблиці Д2 (1.1, 2, 3) — див. l10n_ua_vat_declaration_rare."""
        return False

    def _render_d1_extra(self):
        return ''

    def _render_d2_extra(self):
        return ''

    def _render_d2(self, head):
        """Д2: таблиця 1 (графи 2–6, 10) і рядок «у межах суми за п. 200-1.3»."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]
        rows = self.d2_line_ids.sorted(lambda l: (l.origin_year, l.origin_month,
                                                  l.doc_year, l.doc_month, l.sequence, l.id))

        def column(col, fmt):
            return ''.join(f'<T1RXXXXG{col} ROWNUM="{n}">{fmt(row)}</T1RXXXXG{col}>'
                           for n, row in enumerate(rows, 1))

        body += [
            column('2', lambda r: r.origin_month), column('3', lambda r: r.origin_year),
            column('4', lambda r: r.partner_ipn),
            column('51', lambda r: r.doc_month), column('52', lambda r: r.doc_year),
            column('6', lambda r: _dec2(r.amount)),
            ''.join(f'<T1RXXXXG7 ROWNUM="{n}">1</T1RXXXXG7>'
                    for n, r in enumerate(rows, 1) if r.from_reorg),
        ]
        if any(rows.mapped('debt_amount')):
            body.append(column('8', lambda r: _dec2(r.debt_amount)))
        if any(rows.mapped('refund_amount')):
            body.append(column('9', lambda r: _dec2(r.refund_amount)))
        body += [
            column('10', lambda r: _dec2(r.carry_amount)),
            f'<R01G6>{_int(self.line_19_vat)}</R01G6>',
        ]
        if float_round(self.line_20_1_vat or 0.0, precision_digits=0):
            body.append(f'<R01G8>{_int(self.line_20_1_vat)}</R01G8>')
        if float_round(self.line_20_2_vat or 0.0, precision_digits=0):
            body.append(f'<R01G9>{_int(self.line_20_2_vat)}</R01G9>')
        body.append(f'<R01G10>{_int(self.line_21_vat)}</R01G10>')
        within = (self.line_20_vat or 0.0) - (self.line_20_1_vat or 0.0)
        if float_round(within, precision_digits=0):
            # «Сума, що не перевищує Σнакл, … (р.20 − р.20.1)».
            body.append(f'<R02G3>{_int(within)}</R02G3>')
        body.append(self._render_d2_extra())
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d2'), self._render_head(head), ''.join(body))

    def _attachment_files(self):
        """Додатки пакета: (ключ підпису, base64, ім'я файлу)."""
        self.ensure_one()
        return [(key, self[f'{key}_xml_file'], self[f'{key}_xml_filename'])
                for key in ATTACHMENT_KEYS if self[f'{key}_xml_file']]

    # ------------------------------------------------- контракт dps.submit.mixin

    def action_submit(self):
        """Підписати КЕП у браузері й подати декларацію (з Д1) до ДПС."""
        return self.action_kep_submit()

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Подати можна тільки розраховану декларацію.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати декларацію з ПДВ до ДПС')

    def kep_prepare_signing(self):
        spec = super().kep_prepare_signing()
        for key, data, filename in self._attachment_files():
            doc = dict(spec['documents'][0])
            doc.update(name=key, data_b64=data.decode() if isinstance(data, bytes) else data,
                       filename=filename)
            spec['documents'].append(doc)
        return spec

    def kep_submit_signed(self, signed, auth_signature=None):
        """Декларація з додатками — одним запитом: кабінет приймає масив звітів."""
        self.ensure_one()
        attachments = self._attachment_files()
        if not attachments:
            return super().kep_submit_signed(signed, auth_signature)
        self._dps_check_can_submit()
        config = self._dps_config()
        missing = [key.upper() for key, _d, _f in attachments if not signed.get(key)]
        if not signed.get('doc') or missing:
            raise UserError(_('Не отримано підпис декларації або додатків: %s')
                            % ', '.join(missing or [_('декларація')]))
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
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))
