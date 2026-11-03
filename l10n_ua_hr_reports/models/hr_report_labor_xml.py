"""Електронний 1-ПВ: XML за схемами S0301016 (місячна) і S0301121 (квартальна).

Схеми — з повного пакета СКЗ ДПС 1.34.0.0 (обидві чинні з 2025 року, наказ
Держстату від 15.04.2024 № 117). Заголовок і правила заповнення — «Формат
(стандарт) електронного документа звітності респондентів» Держстату:

* кодування windows-1251, порядок елементів — точно як у схемі;
* C_REG / C_RAJ — код області й району (КАТОТТГ) органу статистики, якому
  подається звіт; C_RAJ доповнюється нулями до 3 знаків;
* PERIOD_TYPE 1 — місяць, 2 — квартал; PERIOD_MONTH — останній місяць
  періоду; D_FILL — ддммрррр;
* ім'я файлу — 37 знаків: C_REG(2) C_RAJ(3) TIN(10) C_DOC C_DOC_SUB
  C_DOC_VER(2) C_DOC_STAN(1) C_DOC_TYPE(2) C_DOC_CNT(5) PERIOD_MONTH(2)
  PERIOD_YEAR.

Подається тим самим каналом, що й податкова звітність (Електронний кабінет
ДПС приймає статистичні форми й передає їх Держстату).
"""
import base64
import re
from datetime import date
from xml.sax.saxutils import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# (C_DOC, C_DOC_SUB, C_DOC_VER, діє з) — найновіша версія першою.
FORM_VERSIONS = {
    'month': [('S03', '010', '16', date(2025, 1, 1))],
    'quarter': [('S03', '011', '21', date(2025, 1, 1))],
}

# Порядок елементів DECLARBODY за XSD. None — службові поля, які заповнює
# _service_values(); решта — показники з рядків звіту.
BODY_ORDER = {
    ('S03', '010', '16'): (
        'FIRM_EDRPOU FIRM_NAME REP_PERNM FIRM_KVED FIRM_ZIP FIRM_OBL FIRM_RAYON '
        'FIRM_TERGROM FIRM_CITY FIRM_RAYGOR FIRM_STREET FIRM_DOM1 FIRM_KORPUS FIRM_KVART '
        'A1020 A1030 A1040 A1060 A1070 NOMER N_1 N_2 OBL RAY KVED N1 N2 VIK_TEL VIK_EMAIL '
        'ZERO_ZVIT REASON KATOTTG_FACT RUK REASON_KOD').split(),
    ('S03', '011', '21'): (
        'FIRM_EDRPOU REP_PERNM FIRM_NAME FIRM_KVED FIRM_ZIP FIRM_OBL FIRM_RAYON '
        'FIRM_TERGROM FIRM_CITY FIRM_RAYGOR FIRM_STREET FIRM_DOM1 FIRM_KORPUS FIRM_KVART '
        'A3020_1 A3020_2 A3040_1 A3040_2 A3050_1 A3050_2 A3060_1 A3060_2 A3070_1 A3070_2 '
        'A3080_1 A3080_2 A3090_2 A4080 A4090 A4100 A5030 A5040 A5050 A5060 A5070 A5080 '
        'A5090 A7010 A7030 A7040 A8010 A8020 A8030 A8040 B4080 B4090 B4100 B7010 B7030 '
        'B7040 C7010 OBL RAY VIK_TEL VIK_EMAIL A5051 A5052 A5010 A5020 A3100_1 A3100_2 '
        'ZERO_ZVIT REASON NOMER N9 N1 N2 REASON_KOD RUK KATOTTG_FACT').split(),
}

# Формат числа за одиницею рядка (типи схеми: тис.грн — DGdecimal1, грн —
# DGdecimal2, особи/години/одиниці — ціле).
UNIT_FORMAT = {'kuah': '%.1f', 'uah': '%.2f', 'persons': '%d', 'hours': '%d', 'units': '%d'}

KATOTTG_RE = re.compile(r'^(?:UA)?(\d{17})$')


def _tag(period_type, section, code, column):
    """Тег XML клітинки звіту: колонки квартальної форми — суфікс _N або літера."""
    if period_type == 'month' or section in ('3', '5'):
        return 'A' + code
    if section == '1':
        return 'A%s_%s' % (code, column)
    return {'1': 'A', '2': 'B', '3': 'C'}[column] + code


class HrReportLabor(models.Model):
    _name = 'hr.report.labor'
    _inherit = ['hr.report.labor', 'l10n_ua.dps.submit.mixin']

    xml_file = fields.Binary(string='XML File', attachment=True, readonly=True, copy=False)
    xml_filename = fields.Char(string='XML File Name', readonly=True, copy=False)
    submission_date = fields.Date(string='Submitted On', readonly=True, copy=False, tracking=True)

    # ------------------------------------------------------------------ дані

    def _form_version(self):
        self.ensure_one()
        for version in FORM_VERSIONS[self.period_type]:
            if self.date_from >= version[3]:
                return version[:3]
        raise UserError(_(
            'Електронна форма 1-ПВ підтримується для звітів з 2025 року '
            '(наказ Держстату № 117).'))

    def _stat_codes(self):
        """(C_REG, C_RAJ) органу статистики з КАТОТТГ компанії або налаштування."""
        self.ensure_one()
        company = self.company_id
        match = KATOTTG_RE.match((company.katottg or '').strip().upper())
        if not match:
            raise UserError(_(
                'Заповніть код КАТОТТГ компанії (UA + 17 цифр): з нього беруться '
                'коди області й району органу статистики.'))
        digits = match.group(1)
        region = digits[:2]
        district = (company.l10n_ua_stat_district_code or '').strip()
        if not district:
            if digits[2:4] == '00':
                # Київ і Севастополь: потрібен код району в місті, з КАТОТТГ
                # міста його не взяти.
                raise UserError(_(
                    'Для міста зі спеціальним статусом укажіть у компанії код району '
                    'органу статистики (3 цифри).'))
            district = digits[2:4]
        return region, district.zfill(3)

    def _tin(self):
        self.ensure_one()
        company = self.company_id
        for value in (company.edrpou, company.company_registry, company.vat):
            digits = re.sub(r'\D', '', value or '')
            if len(digits) in (8, 10):
                return digits
        raise UserError(_('Заповніть код ЄДРПОУ (або РНОКПП ФОП) компанії.'))

    def _service_values(self, region, district, katottg):
        self.ensure_one()
        company = self.company_id
        director = company.director_id if 'director_id' in company._fields else False
        return {
            'FIRM_EDRPOU': self._tin(),
            'FIRM_NAME': company._l10n_ua_dps_name(),
            'FIRM_KVED': company.kved_main,
            'FIRM_ZIP': company.zip,
            'FIRM_CITY': company.city,
            'FIRM_STREET': ' '.join(filter(None, [company.street, company.street2])),
            'OBL': region,
            'RAY': district,
            'KVED': company.kved_main,
            'VIK_TEL': company.phone,
            'VIK_EMAIL': company.email,
            'KATOTTG_FACT': katottg,
            'RUK': director.name if director else False,
        }

    def _cell_values(self):
        """Тег → відформатоване значення для кожного рядка звіту."""
        self.ensure_one()
        values = {}
        for line in self.line_ids:
            tag = _tag(self.period_type, line.section, line.code, line.column_no)
            fmt = UNIT_FORMAT.get(line.unit, '%.2f')
            values[tag] = fmt % (round(line.value) if fmt == '%d' else line.value)
        return values

    def _render_xml(self):
        self.ensure_one()
        c_doc, c_doc_sub, c_doc_ver = self._form_version()
        region, district = self._stat_codes()
        katottg = KATOTTG_RE.match(self.company_id.katottg.strip().upper()).group(1)
        tin = self._tin()
        period_month = self.date_to.month
        head = [
            ('TIN', tin),
            ('C_DOC', c_doc), ('C_DOC_SUB', c_doc_sub), ('C_DOC_VER', c_doc_ver),
            ('C_DOC_TYPE', '0'), ('C_DOC_CNT', '1'),
            ('C_REG', region), ('C_RAJ', district),
            ('PERIOD_MONTH', str(period_month)),
            ('PERIOD_TYPE', '1' if self.period_type == 'month' else '2'),
            ('PERIOD_YEAR', str(self.year)),
            ('D_FILL', fields.Date.context_today(self).strftime('%d%m%Y')),
            ('SOFTWARE', 'Odoo l10n_ua'),
        ]
        values = dict(self._service_values(region, district, katottg))
        values.update(self._cell_values())
        body = [(tag, values[tag]) for tag in BODY_ORDER[(c_doc, c_doc_sub, c_doc_ver)]
                if values.get(tag) not in (None, False, '')]

        def element(tag, value):
            return '<%s>%s</%s>' % (tag, escape(str(value), {'"': '&quot;', "'": '&apos;'}), tag)

        xml = (
            '<?xml version="1.0" encoding="windows-1251"?>\n'
            '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="%s%s%s.xsd">'
            '<DECLARHEAD>%s</DECLARHEAD><DECLARBODY>%s</DECLARBODY></DECLAR>'
        ) % (c_doc, c_doc_sub, c_doc_ver,
             ''.join(element(t, v) for t, v in head),
             ''.join(element(t, v) for t, v in body))
        filename = '%s%s%s%s%s%s1%s%s%02d%d.xml' % (
            region, district, tin.zfill(10), c_doc, c_doc_sub, c_doc_ver,
            '00', '00001', period_month, self.year)
        return xml, filename

    # --------------------------------------------------------------- дії

    def action_export_xml(self):
        for rec in self:
            if not rec.computed_on:
                raise UserError(_('Спочатку розрахуйте звіт.'))
            xml, filename = rec._render_xml()
            rec.write({
                'xml_file': base64.b64encode(xml.encode('windows-1251', errors='replace')),
                'xml_filename': filename,
            })
        return True

    def action_compute(self):
        # Перерахунок робить сформований файл застарілим.
        self.write({'xml_file': False, 'xml_filename': False})
        return super().action_compute()

    # ---------------------------------------- контракт l10n_ua.dps.submit.mixin

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'done':
                raise UserError(_('Позначте звіт виконаним (рядки зафіксуються) перед поданням.'))
            if rec.submission_date:
                raise UserError(_('Звіт уже подано %s.') % rec.submission_date)

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_export_xml()

    def _dps_filename(self):
        # Ім'я за стандартом Держстату, а не за наказом ДПС № 729.
        self.ensure_one()
        return self.xml_filename or 'document.xml'

    def _dps_submit_label(self):
        return _('Подати 1-ПВ до органів статистики')

    def _dps_on_submitted(self, receipt):
        self.write({'state': 'done', 'submission_date': fields.Date.context_today(self)})
        self.activity_feedback(['mail.mail_activity_data_todo'])
        self.message_post(body=_('1-ПВ подано. Квитанція: %s') % (receipt or '—'))

    def action_draft(self):
        if any(rec.submission_date for rec in self):
            raise UserError(_('Поданий звіт не можна повернути в чернетку.'))
        return super().action_draft()


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_ua_stat_district_code = fields.Char(
        string='Statistics District Code', size=3,
        help='Код району (3 цифри) органу статистики для електронних статзвітів '
             '(C_RAJ). Порожньо — береться з КАТОТТГ компанії; для Києва й '
             'Севастополя — обов\'язково (код району в місті).')

    @api.constrains('l10n_ua_stat_district_code')
    def _check_l10n_ua_stat_district_code(self):
        for company in self:
            code = company.l10n_ua_stat_district_code
            if code and not re.fullmatch(r'\d{1,3}', code):
                raise ValidationError(_('Код району органу статистики — до 3 цифр.'))
