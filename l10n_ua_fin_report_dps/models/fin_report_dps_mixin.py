"""XML фінансової звітності за схемами ДПС і подання через кабінет.

Схеми (data/xsd) — з повного пакета СКЗ ДПС 1.34.0.0; за ``spr_ver.xml``
усі чинні без кінцевої дати:

* J0900108 — Баланс (ф. № 1), J0900207 — Звіт про фінрезультати (ф. № 2);
* J0900904 / J0901602 — Звіт про рух грошових коштів, прямий / непрямий метод;
* J0901005 — Звіт про власний капітал (ф. № 4);
* J0901301 — Примітки до річної фінансової звітності (ф. № 5);
* J0901107 / J0901205 — фінзвітність малого підприємства / мікропідприємства.

Рядки форм (R…G…) рахують самі звіти (``_xml_values()`` у l10n_ua_accounting).
Порядок елементів і формат чисел беремо зі схеми, а перед збереженням
перевіряємо документ тією самою схемою — до ДПС не піде файл, який вона
відхилить на структурі.
"""
import base64
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape

from lxml import etree

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import file_path

from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

XS = '{http://www.w3.org/2001/XMLSchema}'
SOFTWARE = 'Odoo l10n_ua'

# Місяць кінця періоду → (PERIOD_TYPE, назва періоду для «за … р.»).
PERIODS = {
    3: (2, 'I квартал'),
    6: (3, 'I півріччя'),
    9: (4, '9 місяців'),
    12: (5, 'рік'),
}
MONTHS_GENITIVE = {
    1: 'січня', 2: 'лютого', 3: 'березня', 4: 'квітня', 5: 'травня', 6: 'червня',
    7: 'липня', 8: 'серпня', 9: 'вересня', 10: 'жовтня', 11: 'листопада', 12: 'грудня',
}
NUMBER_FORMATS = {
    'DGdecimal0': lambda v: '%d' % round(v),
    'DGdecimal1': lambda v: '%.1f' % v,
    'DGdecimal2': lambda v: '%.2f' % v,
}

_SCHEMAS = {}


def _schema(form):
    """(XMLSchema, [(element, type, required)] заголовка, [...] тіла) форми — з кешем."""
    if form not in _SCHEMAS:
        path = file_path('l10n_ua_fin_report_dps/data/xsd/%s.xsd' % form)
        tree = etree.parse(path)

        def elements(type_name):
            """Елементи верхнього рівня типу (зокрема гілки xs:choice), по порядку."""
            sequence = tree.find('.//%scomplexType[@name="%s"]/%ssequence' % (XS, type_name, XS))
            result = []
            for child in sequence:
                group = child if child.tag == XS + 'choice' else None
                for el in (group if group is not None else [child]):
                    if el.tag == XS + 'element':
                        required = el.get('minOccurs') != '0' and group is None
                        result.append((el.get('name'), el.get('type'), required))
            return result

        _SCHEMAS[form] = (etree.XMLSchema(tree), elements('DHead'), elements('DBody'))
    return _SCHEMAS[form]


class L10nUaFinReportDpsMixin(models.AbstractModel):
    """Спільне для форм фінзвітності: XML ДПС, перевірка схемою, подання.

    Модель-споживач визначає ``_fin_dps_form()`` (код форми, напр. J0900108)
    і за потреби ``_fin_dps_header()`` (поля шапки, специфічні для форми).
    """
    _name = 'l10n_ua.fin.report.dps.mixin'
    _inherit = 'l10n_ua.dps.submit.mixin'
    _description = 'Фінзвітність: XML і подання до ДПС'

    xml_file = fields.Binary(string='XML File', attachment=True, readonly=True, copy=False)
    xml_filename = fields.Char(string='XML File Name', readonly=True, copy=False)
    submission_date = fields.Date(string='Submitted On', readonly=True, copy=False)

    # ------------------------------------------------------------ хуки форми

    def _fin_dps_form(self):
        raise NotImplementedError

    def _fin_dps_header(self, period_text):
        """Поля шапки, яких немає в усіх формах (перевизначає споживач)."""
        return {}

    # -------------------------------------------------------------- період

    def _fin_dps_period(self):
        """(PERIOD_TYPE, PERIOD_MONTH, назва періоду) за кінцем періоду звіту.

        Проміжна звітність — наростаючим підсумком з початку року, тож період
        закінчується в кінці кварталу, а звіт за період починається 1 січня.
        """
        self.ensure_one()
        end = self.date_to
        start = self['date_from'] if 'date_from' in self._fields else None
        quarter_end = end.month in PERIODS and (end + timedelta(days=1)).day == 1
        if not quarter_end or (start and start != date(end.year, 1, 1)):
            raise UserError(_(
                'Фінзвітність до ДПС подається за I квартал, півріччя, 9 місяців або '
                'рік: період — з 1 січня до кінця кварталу.'))
        period_type, text = PERIODS[end.month]
        return period_type, end.month, text

    def _fin_dps_balance_date_text(self):
        """«31 грудня» — дата балансу для рядка «Баланс на … р.»."""
        return '%d %s' % (self.date_to.day, MONTHS_GENITIVE[self.date_to.month])

    # ---------------------------------------------------------- реквізити

    def _fin_dps_office(self):
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        return re.sub(r'\D', '', (office.code if office else '') or company.tax_office_code or '')

    def _fin_dps_tin(self):
        company = self.company_id
        return re.sub(r'\D', '', company.edrpou or company.company_registry or '')

    def _fin_dps_kved(self):
        company = self.company_id
        links = company.l10n_ua_kved_ids.sorted(lambda k: (not k.is_primary, k.sequence))
        return (links[:1].code or company.kved_main or '').strip()

    def _fin_dps_signatories(self):
        """(керівник, головний бухгалтер) — з реквізитів компанії."""
        company = self.company_id
        partner = company.partner_id
        chief = partner.l10n_ua_chief_name
        if not chief and 'director_id' in company._fields:
            chief = company.director_id.name
        accountant = partner.l10n_ua_accountant_name
        if not accountant and 'accountant_id' in company._fields:
            accountant = company.accountant_id.name
        return (chief or '').strip(), (accountant or '').strip()

    def _fin_dps_common_header(self, period_text):
        company = self.company_id
        chief, accountant = self._fin_dps_signatories()
        address = ', '.join(filter(None, [company.zip, company.state_id.name, company.city,
                                          company.street, company.street2]))
        phone = re.sub(r'[^0-9 ()\-+.,;]', '', company.phone or '')
        return {
            'HFILL': fields.Date.context_today(self).strftime('%d%m%Y'),
            'HNAME': company._l10n_ua_dps_name(),
            'HTIN': self._fin_dps_tin(),
            'HKOATUU': re.sub(r'\D', '', company.koatuu or ''),
            'HKVED': self._fin_dps_kved(),
            'HLOC': address,
            'HTEL': phone if len(phone) >= 4 else '',
            'HPERIOD': period_text,
            'HZY': str(self.date_to.year),
            'HBOS': chief,
            'HBUH': accountant,
        }

    def _fin_dps_check(self, form, header, body_elements):
        problems = []
        if self.state != 'confirmed':
            problems.append(_('затвердіть звіт (кнопка «Confirm»)'))
        if not re.fullmatch(r'\d{8}', self._fin_dps_tin()):
            problems.append(_('код ЄДРПОУ компанії (8 цифр)'))
        if not re.fullmatch(r'\d{4}', self._fin_dps_office()):
            problems.append(_('податкова інспекція компанії (4-значний код ДПІ)'))
        names = {name for name, _type, _req in body_elements}
        if 'HKOATUU' in names and not re.fullmatch(r'\d{9,10}', header['HKOATUU']):
            problems.append(_('код КОАТУУ компанії (10 цифр) — схема %s його вимагає') % form)
        if 'HKVED' in names and header['HKVED'] \
                and not re.fullmatch(r'\d{2}\.\d{1,2}(\.\d)?', header['HKVED']):
            problems.append(_('основний КВЕД компанії у форматі 00.00'))
        if not header['HBOS']:
            problems.append(_('ПІБ керівника (реквізити компанії)'))
        if problems:
            raise UserError(_('Неможливо сформувати XML %(form)s:\n• %(list)s',
                              form=form, list='\n• '.join(problems)))

    # ----------------------------------------------------------------- XML

    def _fin_dps_render(self):
        self.ensure_one()
        form = self._fin_dps_form()
        schema, head_elements, body_elements = _schema(form)
        period_type, period_month, period_text = self._fin_dps_period()
        header = self._fin_dps_common_header(period_text)
        header.update(self._fin_dps_header(period_text))
        self._fin_dps_check(form, header, body_elements)

        office = self._fin_dps_office()
        tin = self._fin_dps_tin()
        head_values = {
            'TIN': tin, 'C_DOC': form[:3], 'C_DOC_SUB': form[3:6],
            'C_DOC_VER': str(int(form[6:8])), 'C_DOC_TYPE': '0', 'C_DOC_CNT': '1',
            'C_REG': str(int(office[:2])), 'C_RAJ': str(int(office[2:4])),
            'PERIOD_MONTH': str(period_month), 'PERIOD_TYPE': str(period_type),
            'PERIOD_YEAR': str(self.date_to.year), 'C_STI_ORIG': office,
            'C_DOC_STAN': '1', 'D_FILL': header['HFILL'], 'SOFTWARE': SOFTWARE,
        }
        head = []
        for name, _type, required in head_elements:
            if name in head_values:
                head.append(self._fin_dps_element(name, head_values[name]))
            elif required or name == 'LINKED_DOCS':
                head.append('<%s xsi:nil="true"/>' % name)

        values = dict(header)
        values.update(self._xml_values())
        body = []
        for name, type_, _required in body_elements:
            value = values.get(name)
            if value in (None, False, ''):
                continue
            if type_ in NUMBER_FORMATS:
                value = NUMBER_FORMATS[type_](value)
            body.append(self._fin_dps_element(name, value))

        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               'xsi:noNamespaceSchemaLocation="%s.xsd"><DECLARHEAD>%s</DECLARHEAD>'
               '<DECLARBODY>%s</DECLARBODY></DECLAR>') % (form, ''.join(head), ''.join(body))
        content = xml.encode('windows-1251', errors='xmlcharrefreplace')
        doc = etree.fromstring(content)
        if not schema.validate(doc):
            errors = '\n'.join('• %s' % e.message for e in list(schema.error_log)[:5])
            raise UserError(_('XML %(form)s не відповідає схемі ДПС:\n%(errors)s',
                              form=form, errors=errors))
        return content

    @staticmethod
    def _fin_dps_element(name, value):
        return '<%s>%s</%s>' % (name, escape(str(value), {'"': '&quot;', "'": '&apos;'}), name)

    def action_generate_dps_xml(self):
        for rec in self:
            content = rec._fin_dps_render()
            rec.write({'xml_file': base64.b64encode(content),
                       'xml_filename': dps_standard_filename(content)})
        return True

    # --------------------------------------- контракт l10n_ua.dps.submit.mixin

    def _fin_dps_reset(self):
        if any(rec.submission_date for rec in self):
            raise UserError(_('Звіт уже подано до ДПС — змінювати його не можна.'))
        self.write({'xml_file': False, 'xml_filename': False})

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Затвердіть звіт перед поданням.'))
            if rec.submission_date:
                raise UserError(_('Звіт уже подано %s.') % rec.submission_date)

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_dps_xml()

    def _dps_submit_label(self):
        return _('Подати %s до ДПС') % self._fin_dps_form()

    def _dps_on_submitted(self, receipt):
        self.write({'submission_date': fields.Date.context_today(self)})
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))

