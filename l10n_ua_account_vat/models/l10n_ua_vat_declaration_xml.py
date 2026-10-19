"""XML декларації з ПДВ (J0200126) і додатка Д1 (J0200526) та подання до ДПС.

Форма — наказ Мінфіну № 21 у редакції наказу № 400 від 09.08.2024; структура —
XSD з пакета СКЗ ДПС (``tests/schemas``). Рядки основної форми — у цілих гривнях
(DGdecimal0), таблиці додатка — з копійками (Decimal2Column).

Підтримується типовий місяць платника-юрособи: зобов'язання за ПН/РК, податковий
кредит за ПН/РК з розшифровкою за постачальниками (Д1, таблиці 2.1 і 2.2), імпорт.
Не формуються (і тоді XML не будується, щоб не подати неповний пакет): Д1 таблиці
1.1/1.2 (незареєстровані видані ПН/РК), Д2 (від'ємне значення), Д3–Д6.
"""
import base64
import re
from collections import defaultdict
from datetime import date
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

SOFTWARE = 'Odoo l10n_ua'
# C_DOC, C_DOC_SUB, C_DOC_VER
MAIN_FORM = ('J02', '001', '26')
D1_FORM = ('J02', '005', '26')

# Рядки основної форми в порядку XSD: (тег, поле моделі).
MAIN_ROWS = [
    ('R11GA', 'line_1_1_base'), ('R11GB', 'line_1_1_vat'),
    ('R12GA', 'line_1_2_base'), ('R12GB', 'line_1_2_vat'),
    ('R13GA', 'line_1_3_base'), ('R13GB', 'line_1_3_vat'),
    ('R21GA', 'line_2_base'), ('R22GA', 'line_2_2_base'),
    ('R30GA', 'line_3_base'),
    ('R50GA', 'line_5_base'), ('R51GA', 'line_5_1_base'),
    ('R71GA', 'line_7_1_base'), ('R71GB', 'line_7_1_vat'),
    ('R90GB', 'line_9_vat'),
    ('R101GA', 'line_10_1_base'), ('R101GB', 'line_10_1_vat'),
    ('R102GA', 'line_10_2_base'), ('R102GB', 'line_10_2_vat'),
    ('R103GA', 'line_10_3_base'), ('R103GB', 'line_10_3_vat'),
    ('R104GA', 'line_10_4_base'),
    ('R111GA', 'line_11_1_base'), ('R111GB', 'line_11_1_vat'),
    ('R112GA', 'line_11_2_base'), ('R112GB', 'line_11_2_vat'),
    ('R113GA', 'line_11_3_base'), ('R113GB', 'line_11_3_vat'),
    ('R114GA', 'line_11_4_base'),
    ('R140GB', 'line_14_vat'),
    ('R150GB', 'line_15_vat'),
    ('R160GB', 'line_16_1_vat'), ('R161GB', 'line_16_1_vat'),
    ('R170GB', 'line_17_vat'),
    ('R180GB', 'line_18_vat'),
    ('R190GB', 'line_19_vat'),
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

    def _vat_head(self, form, linked=None):
        """Реквізити DECLARHEAD; ``linked`` — (форма, ім'я файлу, TYPE) пов'язаного."""
        self.ensure_one()
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        office_code = re.sub(r'\D', '', (office.code if office else '')
                             or company.tax_office_code or '')
        period = self.period_id
        return {
            'tin': re.sub(r'\D', '', company.edrpou or ''),
            'c_doc': form[0], 'c_doc_sub': form[1], 'c_doc_ver': form[2],
            'c_doc_type': 0, 'c_doc_cnt': 1, 'c_doc_stan': '1',
            'c_reg': office_code[:2], 'c_raj': office_code[2:4],
            'period_month': period.date_end.month, 'period_type': '1',
            'period_year': period.date_end.year, 'c_sti_orig': office_code,
            'office_name': office.name if office else '',
            'linked': linked,
        }

    def _check_vat_xml_ready(self):
        """Помилки до формування — усе, чого бракує, одним повідомленням."""
        self.ensure_one()
        company = self.company_id
        problems = []
        if company.l10n_ua_is_fop:
            problems.append(_('декларація ФОП-платника ПДВ (F0200126) ще не формується'))
        period = self.period_id
        if not period.date_start or not period.date_end or \
                period.date_start.month != period.date_end.month:
            problems.append(_('XML формується лише за місячний період'))
        # Odoo 20: поля company_registry немає, ЄДРПОУ — лише edrpou.
        if not re.sub(r'\D', '', company.edrpou or ''):
            problems.append(_('код ЄДРПОУ компанії'))
        if not re.fullmatch(r'\d{12}', company.l10n_ua_vat_ipn or ''):
            problems.append(_('ІПН платника ПДВ компанії (12 цифр)'))
        office = company.l10n_ua_tax_office_id
        if not re.fullmatch(r'\d{4}', re.sub(r'\D', '', (office.code if office else '')
                                              or company.tax_office_code or '')):
            problems.append(_('податкова інспекція компанії (4-значний код ДПІ)'))
        if not self.signatory_name or not re.fullmatch(r'\d{10}', self.signatory_rnokpp or ''):
            problems.append(_('керівник і його РНОКПП (вкладка «Подання»)'))
        unregistered = (self.register_issued_id.line_ids.tax_invoice_id
                        .filtered(lambda i: i.state != 'registered'))
        if unregistered:
            problems.append(_(
                'видані ПН/РК не зареєстровані в ЄРПН (%s) — для них потрібні таблиці '
                '1.1/1.2 додатка Д1, які ще не формуються')
                % ', '.join(unregistered.mapped('display_name')[:5]))
        if self.line_19_vat:
            problems.append(_('від\'ємне значення (рядок 19) потребує додатка Д2, '
                              'який ще не формується'))
        no_ipn = self._d1_lines().filtered(
            lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or ''))
        if no_ipn:
            problems.append(_('ІПН постачальників: %s')
                            % ', '.join(no_ipn.partner_id.mapped('display_name')[:5]))
        if problems:
            raise UserError(_('Неможливо сформувати XML декларації з ПДВ:\n• %s')
                            % '\n• '.join(problems))

    def _d1_lines(self):
        """Рядки реєстру отриманих, що розшифровуються в Д1 (без імпорту)."""
        return self.register_received_id.line_ids.filtered(
            lambda l: not l.tax_invoice_id.is_import)

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

    def action_generate_xml(self):
        for rec in self:
            rec._check_vat_xml_ready()
            t21, t22 = rec._d1_tables()
            main_head = rec._vat_head(MAIN_FORM)
            vals = {}
            if t21 or t22:
                d1_head = rec._vat_head(D1_FORM)
                main_name = _filename(main_head)
                d1_name = _filename(d1_head)
                main_head['linked'] = (D1_FORM, d1_name, 1)
                d1_head['linked'] = (MAIN_FORM, main_name, 2)
                d1_xml = rec._render_d1(d1_head, t21, t22)
                # Odoo 20: Binary приймає base64-рядок (bytes — TypeError).
                vals.update(d1_xml_file=base64.b64encode(d1_xml).decode(),
                            d1_xml_filename=dps_standard_filename(d1_xml))
            else:
                vals.update(d1_xml_file=False, d1_xml_filename=False)
            main_xml = rec._render_main(main_head, has_d1=bool(t21 or t22))
            vals.update(xml_file=base64.b64encode(main_xml).decode(),
                        xml_filename=dps_standard_filename(main_xml))
            rec.write(vals)
        return True

    def _render_head(self, head):
        linked = head['linked']
        if linked:
            form, fname, link_type = linked
            linked_xml = (
                '<LINKED_DOCS><DOC NUM="1" TYPE="%s"><C_DOC>%s</C_DOC><C_DOC_SUB>%s</C_DOC_SUB>'
                '<C_DOC_VER>%s</C_DOC_VER><C_DOC_TYPE>0</C_DOC_TYPE><C_DOC_CNT>1</C_DOC_CNT>'
                '<C_DOC_STAN>1</C_DOC_STAN><FILENAME>%s</FILENAME></DOC></LINKED_DOCS>'
                % (link_type, form[0], form[1], form[2], fname[:-4] + '.XML'))
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

    def _render_main(self, head, has_d1):
        self.ensure_one()
        company = self.company_id
        address = ', '.join(filter(None, [company.zip, company.state_id.name, company.city,
                                          company.street, company.street2]))
        body = [self._render_taxpayer(head), f'<HLOC>{escape(address)}</HLOC>']
        if company.zip:
            body.append(f'<HZIP>{escape(company.zip)}</HZIP>')
        body.append(f'<HSTI>{escape(head["office_name"])}</HSTI>')
        for tag, field in MAIN_ROWS:
            value = self[field]
            if float_round(value or 0.0, precision_digits=0):
                body.append(f'<{tag}>{_int(value)}</{tag}>')
        if has_d1:
            body.append('<HD1>1</HD1>')
        body.append(self._render_signers())
        return self._wrap(MAIN_FORM, self._render_head(head), ''.join(body))

    def _render_d1(self, head, t21, t22):
        """Д1: таблиці 2.1 і 2.2 — стовпцями з ROWNUM, як вимагає XSD."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]

        def column(prefix, col, rows, fmt):
            return ''.join(f'<{prefix}RXXXXG{col} ROWNUM="{n}">{fmt(row)}</{prefix}RXXXXG{col}>'
                           for n, row in enumerate(rows, 1))

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
        return self._wrap(D1_FORM, self._render_head(head), ''.join(body))

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
        if self.d1_xml_file:
            doc = dict(spec['documents'][0])
            # Odoo 20: BinaryValue — base64 через to_base64().
            doc.update(name='d1', data_b64=self.d1_xml_file.to_base64(),
                       filename=self.d1_xml_filename)
            spec['documents'].append(doc)
        return spec

    def kep_submit_signed(self, signed, auth_signature=None):
        """Декларація і Д1 — одним запитом: кабінет приймає масив звітів."""
        self.ensure_one()
        if not self.d1_xml_file:
            return super().kep_submit_signed(signed, auth_signature)
        self._dps_check_can_submit()
        config = self._dps_config()
        if not signed.get('doc') or not signed.get('d1'):
            raise UserError(_('Не отримано підпис декларації або додатка Д1.'))
        result = config._api_submit_document_presigned(
            signed['doc'], self._dps_filename(), auth_signature,
            extra_files=[(signed['d1'], self.d1_xml_filename)])
        self._dps_check_result(result)
        receipt = self._dps_receipt_text(result)
        self._dps_store_receipts(result)
        self._dps_on_submitted(receipt)
        return {'receipt': receipt}

    def _dps_on_submitted(self, receipt):
        self.write({'state': 'submitted', 'submission_date': fields.Date.context_today(self)})
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))
