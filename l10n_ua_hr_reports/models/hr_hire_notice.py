"""Повідомлення ДПС про прийняття працівника на роботу (#369).

Правова основа
--------------
* КЗпП, ч. 3 ст. 24 — трудовий договір недійсний без повідомлення ДПС до
  початку роботи; ч. 2 ст. 173-3 — домашні працівники.
* Постанова КМУ від 17.06.2015 № 413 (ред. від 21.01.2026, зміни № 41 від
  07.01.2026) — повідомлення подає роботодавець або резидент Дія Сіті до
  територіального органу ДПС за місцем обліку платника ЄСВ, **до початку
  роботи** (для гіг-контракту — до початку виконання робіт), засобами
  електронного зв'язку з КЕП. Керівника / члена виконавчого органу
  господарського товариства не повідомляють: ДПС бере ці дані з ЄДР.
* Форма — додаток 1 до Постанови № 413 у ред. постанови КМУ від 21.02.2025
  № 184 (графи 1–15, категорії осіб 1–5, графа 9 «Громадянство»).
* Електронна форма ДПС: J3001005 (юр. особи) / F3001005 (фіз. особи), реєстр
  електронних форм ДПС (data.gov.ua, датасет f0b2d3a3-…, рядки 73/127) і
  новини ГУ ДПС (з 01.05.2025). C_DOC=J30, C_DOC_SUB=010, C_DOC_VER=5.

Статус XML
----------
Конверт (DECLARHEAD) — як у решти форм ДПС у репозиторії (J0510210,
J1300205, звірені з XSD). Назви елементів DECLARBODY **не звірені** з
офіційним XSD J3001005 (пакет СКЗ на tax.gov.ua недоступний автоматизації —
403). Їх зібрано в ``BODY_TAGS`` за конвенцією форм ДПС (H* — шапка,
T1RXXXXG<графа> — таблиця, HKBOS/HBOS/HKBUH/HBUH/HFILL — підписанти);
після отримання XSD — вендорити його в tests/schemas/J3001005.xsd: тест
``test_xml_validates_against_xsd_if_vendored`` почне валідувати автоматично.
"""

import base64
import re
from datetime import date, timedelta
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

HIRE_NOTICE_C_DOC_SUB = '010'
HIRE_NOTICE_C_DOC_VER = '5'
HIRE_NOTICE_SOFTWARE = 'Odoo l10n_ua'

# Назви елементів тіла J3001005 (НЕ звірені з XSD — див. docstring модуля).
# Ключ = графа форми (додаток 1 до Постанови № 413 у ред. № 184).
BODY_TAGS = {
    'type_initial': 'HPOCH',      # гр. 1 «початкове»
    'type_cancel': 'HSKAS',       # гр. 1 «скасовуюче»
    'tin': 'HTIN',                # гр. 2 код ЄДРПОУ / РНОКПП страхувальника
    'name': 'HNAME',              # гр. 3 найменування страхувальника
    'row': 'T1RXXXXG4',           # гр. 4 порядковий номер
    'category': 'T1RXXXXG5',      # гр. 5 категорія особи (1..5)
    'person_tin': 'T1RXXXXG6S',   # гр. 6 РНОКПП / серія+номер паспорта
    'unzr': 'T1RXXXXG7S',         # гр. 7 УНЗР
    'person_name': 'T1RXXXXG8S',  # гр. 8 ПІБ
    'citizenship': 'T1RXXXXG9',   # гр. 9 громадянство (0/1)
    'order_number': 'T1RXXXXG10S',  # гр. 10 номер наказу
    'order_date': 'T1RXXXXG11D',  # гр. 11 дата наказу / договору
    'date_start': 'T1RXXXXG12D',  # гр. 12 дата початку роботи
    'date_formed': 'T1RXXXXG13D',  # гр. 13 дата формування
    'hkbos': 'HKBOS',             # гр. 14 РНОКПП керівника
    'hbos': 'HBOS',               # гр. 14 ім'я керівника
    'hkbuh': 'HKBUH',             # гр. 15 РНОКПП головного бухгалтера
    'hbuh': 'HBUH',               # гр. 15 ім'я головного бухгалтера
    'hfill': 'HFILL',
}

# Категорія особи (гр. 5, виноска ** до форми):
# 1 — наймані працівники за основним місцем роботи; 2 — за сумісництвом;
# 3 — гіг-спеціалісти за гіг-контрактом; 4 — особи за ЦПД;
# 5 — домашні працівники.
PERSON_CATEGORIES = [
    ('1', '1 - Employee (main place of work)'),
    ('2', '2 - Employee (concurrent employment)'),
    ('3', '3 - Gig specialist (Diia.City gig contract)'),
    ('4', '4 - Civil law contract'),
    ('5', '5 - Domestic worker'),
]

# Категорії, для яких операційна частина Постанови № 413 прямо вимагає
# повідомлення до початку роботи (трудовий договір, гіг-контракт). ЦПД
# (категорія 4) форма № 184 допускає, але обов'язку в тексті Порядку нема —
# генеруємо на вимогу, без контролю строку.
MANDATORY_CATEGORIES = ('1', '2', '3')

# Скільки днів наперед нагадувати про подання (cron).
REMINDER_LOOKAHEAD_DAYS = 3


def _digits(value):
    return re.sub(r'\D', '', value or '')


class HrHireNotice(models.Model):
    _name = 'hr.hire.notice'
    _description = 'Hire Notice to the Tax Authority'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        domain="[('company_id', 'in', (company_id, False))]")
    order_id = fields.Many2one(
        'hr.order', string='Hiring Order', tracking=True, index=True,
        domain="[('order_type', '=', 'hiring'), ('employee_id', '=', employee_id)]")
    version_id = fields.Many2one(
        'hr.version', string='Contract',
        domain="[('employee_id', '=', employee_id)]",
        help='Contract version the notice reports (start date, contract type).')

    notice_type = fields.Selection([
        ('initial', 'Initial'),
        ('cancel', 'Cancelling'),
    ], string='Notice Type', default='initial', required=True, tracking=True)
    person_category = fields.Selection(
        PERSON_CATEGORIES, string='Person Category', required=True,
        default='1', tracking=True,
        help='Column 5 of the form (CMU Resolution No. 413 as amended by '
             'No. 184 of 21.02.2025).')
    citizenship = fields.Selection([
        ('1', '1 - Citizen of Ukraine'),
        ('0', '0 - Foreigner or stateless person'),
    ], string='Citizenship', default='1', required=True)
    person_tin = fields.Char(
        string='RNOKPP / Passport',
        help='Taxpayer card number, or passport series and number for '
             'persons who refused the RNOKPP for religious reasons.')
    unzr = fields.Char(string='UNZR', help='Unique record number in the '
                       'Unified State Demographic Register (if any).')
    person_name = fields.Char(string='Full Name')
    order_number = fields.Char(
        string='Order Number',
        help='Not filled for gig and civil law contracts (column 10).')
    order_date = fields.Date(
        string='Order / Contract Date',
        help='Date of the hiring order, or of the gig / civil law contract '
             '(column 11).')
    date_start = fields.Date(
        string='Work Start Date', required=True, tracking=True,
        help='Column 12. The notice must be filed before this date.')
    date_formed = fields.Date(
        string='Formed On', default=fields.Date.context_today,
        help='Column 13: date the notice was formed.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True,
        copy=False)
    is_mandatory = fields.Boolean(
        string='Mandatory', compute='_compute_is_mandatory', store=True,
        help='The Procedure requires this notice before work starts '
             '(employment and gig contracts).')
    is_overdue = fields.Boolean(
        string='Overdue', readonly=True, copy=False,
        help='Work has started and the notice has not been sent.')
    doc_cnt = fields.Integer(string='Document No. in Period', copy=False,
                             readonly=True)
    xml_file = fields.Binary(string='XML File', attachment=True, copy=False)
    xml_filename = fields.Char(copy=False)
    submission_date = fields.Date(string='Submission Date', copy=False)
    receipt_number = fields.Char(string='Receipt Number', copy=False,
                                 tracking=True)
    notes = fields.Text(string='Notes')

    @api.depends('employee_id', 'date_start', 'notice_type')
    def _compute_name(self):
        for rec in self:
            prefix = (_('Cancelling hire notice') if rec.notice_type == 'cancel'
                      else _('Hire notice'))
            rec.name = '%s: %s%s' % (
                prefix, rec.employee_id.name or '',
                (' (%s)' % rec.date_start.strftime('%d.%m.%Y'))
                if rec.date_start else '')

    @api.depends('person_category')
    def _compute_is_mandatory(self):
        for rec in self:
            rec.is_mandatory = rec.person_category in MANDATORY_CATEGORIES

    # ------------------------------------------------------------------
    # Заповнення з наказу / договору
    # ------------------------------------------------------------------

    @api.model
    def _category_from(self, version, order=False):
        """Категорія особи (гр. 5) з типу договору / форми зайнятості."""
        contract_type = version.sudo().contract_type_ua if version else False
        if contract_type == 'gig':
            return '3'
        if contract_type in ('civil', 'author'):
            return '4'
        if order and order.employment_form:
            return '2' if order.employment_form == 'secondary' else '1'
        employment = version.sudo().employment_type_ua if version else False
        return '2' if employment in ('internal', 'external') else '1'

    @api.model
    def _employee_values(self, employee):
        employee = employee.sudo()
        tin = _digits(employee.rnokpp)
        if not tin:
            # Виноска * до форми: серія (за наявності) та номер паспорта.
            tin = '%s%s' % (employee.passport_series or '',
                            employee.passport_id or '')
        country = employee.country_id
        return {
            'person_tin': tin.upper(),
            'unzr': employee.passport_record_number or False,
            'person_name': employee.name or '',
            'citizenship': '1' if (not country or country.code == 'UA') else '0',
        }

    @api.model
    def _excluded_reason(self, employee, company):
        """Чому повідомлення не подається (або False).

        Абз. 6 постановляючої частини Постанови № 413: повідомленням про
        прийняття керівника / члена виконавчого органу є відомості з ЄДР.
        """
        if employee and company and company.director_id == employee:
            return _('The head of the company is not reported: the tax '
                     'authority takes this data from the Unified State '
                     'Register (CMU Resolution No. 413).')
        return False

    @api.model
    def _order_version(self, order):
        """Версія договору, яку документує наказ (лише читання).

        Та сама логіка, що в ``hr.order._find_hiring_version``, але без її
        побічного ефекту (очищення «чужого» номера наказу на версіях).
        """
        start = order.date_start or order.date
        versions = order.employee_id.sudo().version_ids
        on_date = versions.filtered(lambda v: v.date_version == start)[:1]
        if on_date:
            return on_date
        if order.name and order.name != 'New':
            return versions.filtered(
                lambda v: v.hire_order_number == order.name)[:1]
        return versions.browse()

    @api.model
    def _values_from_order(self, order):
        if order.order_type != 'hiring' or not order.employee_id:
            raise UserError(_('A hire notice is created from a hiring order '
                              'with an employee.'))
        date_start = order.date_start or order.date
        version = self._order_version(order)
        category = self._category_from(version, order)
        vals = {
            'company_id': order.company_id.id,
            'employee_id': order.employee_id.id,
            'order_id': order.id,
            'version_id': version.id or False,
            'person_category': category,
            'order_number': (order.name if category in ('1', '2')
                             and order.name != 'New' else False),
            'order_date': order.date,
            'date_start': date_start,
        }
        vals.update(self._employee_values(order.employee_id))
        return vals

    @api.model
    def _values_from_version(self, version):
        version = version.sudo()
        category = self._category_from(version)
        start = version.contract_date_start or version.date_version
        vals = {
            'company_id': version.company_id.id or version.employee_id.company_id.id,
            'employee_id': version.employee_id.id,
            'version_id': version.id,
            'person_category': category,
            'order_number': (version.hire_order_number
                             if category in ('1', '2') else False),
            'order_date': (version.hire_order_date if category in ('1', '2')
                           else start),
            'date_start': start,
        }
        vals.update(self._employee_values(version.employee_id))
        return vals

    @api.model
    def create_from_order(self, order):
        """Створити (або повернути наявне) повідомлення для наказу."""
        order.ensure_one()
        reason = self._excluded_reason(order.employee_id, order.company_id)
        if reason:
            raise UserError(reason)
        existing = self.search([
            ('order_id', '=', order.id),
            ('notice_type', '=', 'initial'),
            ('state', '!=', 'rejected'),
        ], limit=1)
        if existing:
            return existing
        return self.create(self._values_from_order(order))

    @api.model
    def create_from_version(self, version):
        version.ensure_one()
        employee = version.employee_id
        reason = self._excluded_reason(employee, version.company_id or employee.company_id)
        if reason:
            raise UserError(reason)
        return self.create(self._values_from_version(version))

    @api.onchange('order_id')
    def _onchange_order_id(self):
        if self.order_id and self.order_id.order_type == 'hiring':
            vals = self._values_from_order(self.order_id)
            vals.pop('company_id', None)
            self.update(vals)

    @api.onchange('version_id')
    def _onchange_version_id(self):
        if self.version_id and not self.order_id:
            vals = self._values_from_version(self.version_id)
            vals.pop('company_id', None)
            self.update(vals)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.update(self._employee_values(self.employee_id))

    # ------------------------------------------------------------------
    # XML
    # ------------------------------------------------------------------

    def _notice_vals(self):
        """Реквізити повідомлення; відсутні обов'язкові — UserError."""
        self.ensure_one()
        company = self.company_id
        reason = self._excluded_reason(self.employee_id, company)
        if reason:
            raise UserError(reason)
        tin = _digits(company.edrpou or company.company_registry or company.vat)
        office = _digits(company.tax_office_code)
        director = company.director_id.sudo()
        accountant = company.accountant_id.sudo()
        hkbos = _digits(director.rnokpp) if director else ''
        hkbuh = _digits(accountant.rnokpp) if accountant else ''

        missing = []
        if not tin:
            missing.append(_('company EDRPOU'))
        if len(office) < 4:
            missing.append(_('company tax office code'))
        if not (director and hkbos and director.name):
            missing.append(_('director (with RNOKPP) of the company'))
        if not self.person_tin:
            missing.append(_('employee RNOKPP or passport'))
        if not self.person_name:
            missing.append(_('employee full name'))
        if not self.date_start:
            missing.append(_('work start date'))
        if self.person_category in ('1', '2') and not self.order_number:
            missing.append(_('hiring order number'))
        if not self.order_date:
            missing.append(_('order / contract date'))
        if missing:
            raise UserError(_('To generate the hire notice fill in: %s.')
                            % ', '.join(missing))

        formed = self.date_formed or fields.Date.context_today(self)
        prefix = 'F' if len(tin) == 10 else 'J'
        # Гр. 15 не заповнюється для домашнього працівника (виноска *****).
        with_accountant = bool(accountant and hkbuh
                               and self.person_category != '5')
        return {
            'c_doc': prefix + '30',
            'c_doc_sub': HIRE_NOTICE_C_DOC_SUB,
            'c_doc_ver': HIRE_NOTICE_C_DOC_VER,
            'c_doc_cnt': self.doc_cnt or 1,
            'tin': tin,
            'c_reg': int(office[:2]),
            'c_raj': int(office[2:4]),
            'c_sti_orig': office[:4],
            'period_month': formed.month,
            'period_type': 1,
            'period_year': formed.year,
            'd_fill': formed.strftime('%d%m%Y'),
            'notice_type': self.notice_type,
            'hname': company.name or '',
            'rows': [{
                'category': self.person_category,
                'person_tin': self.person_tin,
                'unzr': self.unzr or '',
                'person_name': self.person_name,
                'citizenship': self.citizenship,
                # Гр. 10 не заповнюється для гіг/ЦПД/домашнього працівника.
                'order_number': (self.order_number
                                 if self.person_category in ('1', '2') else ''),
                'order_date': self.order_date.strftime('%d%m%Y'),
                'date_start': self.date_start.strftime('%d%m%Y'),
                'date_formed': formed.strftime('%d%m%Y'),
            }],
            'hkbos': hkbos,
            'hbos': director.name or '',
            'hkbuh': hkbuh if with_accountant else '',
            'hbuh': (accountant.name or '') if with_accountant else '',
        }

    @api.model
    def _xml_filename(self, vals):
        """Ім'я файлу за правилом ДПС: C_REG C_RAJ TIN(10) C_DOC C_DOC_SUB
        C_DOC_VER(2) C_DOC_STAN C_DOC_TYPE(2) C_DOC_CNT(7) PERIOD_TYPE
        PERIOD_MONTH(2) PERIOD_YEAR C_STI_ORIG(4).xml"""
        return '%02d%02d%s%s%s%02d%d%02d%07d%d%02d%04d%s.xml' % (
            vals['c_reg'], vals['c_raj'], vals['tin'].zfill(10),
            vals['c_doc'], vals['c_doc_sub'], int(vals['c_doc_ver']),
            1, 0, vals['c_doc_cnt'], vals['period_type'],
            vals['period_month'], vals['period_year'],
            vals['c_sti_orig'].zfill(4))

    @api.model
    def _render_notice_xml(self, vals):
        """Стейтлес-рендер XML J3001005/F3001005 (кодування windows-1251)."""
        def esc(v):
            return escape(str(v or ''))

        t = BODY_TAGS
        rows = vals.get('rows') or []

        def column(key, tag):
            out = []
            for i, row in enumerate(rows, 1):
                val = i if key == 'row' else row.get(key)
                if val in (None, ''):
                    continue
                out.append('        <%s ROWNUM="%d">%s</%s>' % (
                    tag, i, esc(val), tag))
            return out

        body = []
        if vals.get('notice_type') == 'cancel':
            body.append('        <%s>1</%s>' % (t['type_cancel'], t['type_cancel']))
        else:
            body.append('        <%s>1</%s>' % (t['type_initial'], t['type_initial']))
        body.append('        <%s>%s</%s>' % (t['tin'], esc(vals['tin']), t['tin']))
        body.append('        <%s>%s</%s>' % (t['name'], esc(vals['hname']), t['name']))
        for key in ('row', 'category', 'person_tin', 'unzr', 'person_name',
                    'citizenship', 'order_number', 'order_date', 'date_start',
                    'date_formed'):
            body.extend(column(key, t[key]))
        for key in ('hkbos', 'hbos', 'hkbuh', 'hbuh'):
            if vals.get(key):
                body.append('        <%s>%s</%s>' % (t[key], esc(vals[key]), t[key]))
        body.append('        <%s>%s</%s>' % (t['hfill'], vals['d_fill'], t['hfill']))

        head = [
            '<?xml version="1.0" encoding="windows-1251"?>',
            '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:noNamespaceSchemaLocation="%s%s%02d.xsd">' % (
                vals['c_doc'], vals['c_doc_sub'], int(vals['c_doc_ver'])),
            '    <DECLARHEAD>',
            '        <TIN>%s</TIN>' % esc(vals['tin']),
            '        <C_DOC>%s</C_DOC>' % vals['c_doc'],
            '        <C_DOC_SUB>%s</C_DOC_SUB>' % vals['c_doc_sub'],
            '        <C_DOC_VER>%s</C_DOC_VER>' % vals['c_doc_ver'],
            '        <C_DOC_TYPE>0</C_DOC_TYPE>',
            '        <C_DOC_CNT>%s</C_DOC_CNT>' % vals['c_doc_cnt'],
            '        <C_REG>%s</C_REG>' % vals['c_reg'],
            '        <C_RAJ>%s</C_RAJ>' % vals['c_raj'],
            '        <PERIOD_MONTH>%s</PERIOD_MONTH>' % vals['period_month'],
            '        <PERIOD_TYPE>%s</PERIOD_TYPE>' % vals['period_type'],
            '        <PERIOD_YEAR>%s</PERIOD_YEAR>' % vals['period_year'],
            '        <C_STI_ORIG>%s</C_STI_ORIG>' % esc(vals['c_sti_orig']),
            '        <C_DOC_STAN>1</C_DOC_STAN>',
            '        <D_FILL>%s</D_FILL>' % vals['d_fill'],
            '        <SOFTWARE>%s</SOFTWARE>' % HIRE_NOTICE_SOFTWARE,
            '    </DECLARHEAD>',
            '    <DECLARBODY>',
        ]
        return '\n'.join(head + body + ['    </DECLARBODY>', '</DECLAR>'])

    def _next_doc_cnt(self):
        """Порядковий номер документа цього типу в періоді (C_DOC_CNT)."""
        self.ensure_one()
        formed = self.date_formed or fields.Date.context_today(self)
        start = formed.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1)
        others = self.search([
            ('company_id', '=', self.company_id.id),
            ('id', '!=', self.id),
            ('doc_cnt', '>', 0),
            ('date_formed', '>=', start),
            ('date_formed', '<', end),
        ])
        return max(others.mapped('doc_cnt') or [0]) + 1

    def action_generate_xml(self):
        for rec in self:
            if rec.state not in ('draft', 'generated', 'rejected'):
                raise UserError(_('A sent notice cannot be regenerated.'))
            if not rec.date_formed:
                rec.date_formed = fields.Date.context_today(rec)
            if not rec.doc_cnt:
                rec.doc_cnt = rec._next_doc_cnt()
            vals = rec._notice_vals()
            xml = rec._render_notice_xml(vals)
            rec.write({
                'xml_file': base64.b64encode(xml.encode('windows-1251')),
                'xml_filename': rec._xml_filename(vals),
                'state': 'generated',
            })
            rec.message_post(body=_('Hire notice XML generated: %s')
                             % rec.xml_filename)
        return True

    def action_download_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/xml_file/%s?download=true' % (
                self._name, self.id, self.xml_filename),
            'target': 'self',
        }

    # ------------------------------------------------------------------
    # Стани / подання
    # ------------------------------------------------------------------

    def action_submit(self):
        """КЕП-підпис у браузері і подання до Електронного кабінету ДПС."""
        return self.action_kep_submit()

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'generated':
                raise UserError(_('Generate the notice XML before sending.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Send hire notice to the tax authority')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'sent',
            'submission_date': fields.Date.context_today(self),
            'is_overdue': False,
        })
        self.message_post(body=_('Sent to the tax authority. Receipt: %s')
                          % (receipt or '-'))

    def action_mark_sent(self):
        """Позначити подання, зроблене поза Odoo (напр. в Е-кабінеті)."""
        for rec in self:
            if rec.state not in ('generated', 'draft'):
                raise UserError(_('Only a draft or generated notice can be '
                                  'marked as sent.'))
        self.write({
            'state': 'sent',
            'submission_date': fields.Date.context_today(self),
            'is_overdue': False,
        })

    def action_mark_accepted(self):
        if self.filtered(lambda r: r.state != 'sent'):
            raise UserError(_('Only a sent notice can be accepted.'))
        self.write({'state': 'accepted'})

    def action_mark_rejected(self):
        if self.filtered(lambda r: r.state != 'sent'):
            raise UserError(_('Only a sent notice can be rejected.'))
        self.write({'state': 'rejected'})

    def action_draft(self):
        if self.filtered(lambda r: r.state in ('sent', 'accepted')):
            raise UserError(_('A sent notice cannot be reset to draft; file a '
                              'cancelling notice instead.'))
        self.write({'state': 'draft', 'xml_file': False, 'xml_filename': False})

    def action_create_cancelling(self):
        """Скасовуюче повідомлення (гр. 1) до поданого."""
        self.ensure_one()
        if self.state not in ('sent', 'accepted'):
            raise UserError(_('Only a sent notice can be cancelled.'))
        new = self.copy({
            'notice_type': 'cancel',
            'date_formed': fields.Date.context_today(self),
            'doc_cnt': 0,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new.id,
            'view_mode': 'form',
        }

    # ------------------------------------------------------------------
    # Контроль строку (cron)
    # ------------------------------------------------------------------

    @api.model
    def _hiring_orders_without_notice(self, until):
        """Накази про прийняття, робота за якими починається до ``until``,
        а поданого / прийнятого повідомлення нема."""
        since = until - timedelta(days=REMINDER_LOOKAHEAD_DAYS + 31)
        orders = self.env['hr.order'].search([
            ('order_type', '=', 'hiring'),
            ('state', '!=', 'cancelled'),
            ('employee_id', '!=', False),
            '|',
            '&', ('date_start', '!=', False), ('date_start', '>=', since),
            '&', ('date_start', '=', False), ('date', '>=', since),
        ])
        result = self.env['hr.order']
        for order in orders:
            start = order.date_start or order.date
            if not start or start > until:
                continue
            if self._excluded_reason(order.employee_id, order.company_id):
                continue
            version = self._order_version(order)
            if self._category_from(version, order) not in MANDATORY_CATEGORIES:
                continue
            done = self.search_count([
                ('order_id', '=', order.id),
                ('notice_type', '=', 'initial'),
                ('state', 'in', ('sent', 'accepted')),
            ])
            if not done:
                result |= order
        return result

    @api.model
    def _reminder_summaries(self):
        """Заголовок нагадування: англійський і в мові поточного користувача.

        Дедуплікація звіряє обидва, щоб зміна мови користувача cron не
        породжувала повторних активностей; останній — для нових активностей.
        """
        source = 'Hire notice to the tax authority'
        return (source, _('Hire notice to the tax authority'))

    @api.model
    def _cron_check_hire_notice_deadlines(self):
        """Щоденний контроль строку: повідомлення — до початку роботи.

        * Наказ про прийняття, робота за яким починається протягом
          ``REMINDER_LOOKAHEAD_DAYS`` днів (або вже почалась у межах місяця),
          а поданого повідомлення нема — активність на наказі.
        * Неподані обов'язкові повідомлення з датою початку роботи в минулому
          — позначка «прострочено» і нагадування у чатері.
        """
        today = fields.Date.context_today(self)
        until = today + timedelta(days=REMINDER_LOOKAHEAD_DAYS)
        summaries = self._reminder_summaries()
        summary = summaries[-1]
        for order in self._hiring_orders_without_notice(until):
            start = order.date_start or order.date
            if start < today - timedelta(days=31):
                continue  # давні накази — не засмічуємо нагадуваннями
            if order.activity_ids.filtered(lambda a: a.summary in summaries):
                continue
            order.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=summary,
                note=_('File the hire notice for %(employee)s before work '
                       'starts on %(date)s (CMU Resolution No. 413, '
                       'Labour Code art. 24).',
                       employee=order.employee_id.name,
                       date=start.strftime('%d.%m.%Y')),
                date_deadline=max(start - timedelta(days=1), today),
                user_id=(order.confirmed_by_id or order.create_uid
                         or self.env.user).id,
            )

        overdue = self.search([
            ('state', 'in', ('draft', 'generated')),
            ('notice_type', '=', 'initial'),
            ('is_mandatory', '=', True),
            ('is_overdue', '=', False),
            ('date_start', '<', today),
        ])
        if overdue:
            overdue.write({'is_overdue': True})
            for rec in overdue:
                rec.message_post(body=_(
                    'The hire notice for %(employee)s was not sent before '
                    'work started on %(date)s (CMU Resolution No. 413).',
                    employee=rec.employee_id.name,
                    date=rec.date_start.strftime('%d.%m.%Y')))
        return True


class HrOrder(models.Model):
    _inherit = 'hr.order'

    hire_notice_ids = fields.One2many(
        'hr.hire.notice', 'order_id', string='Hire Notices')
    hire_notice_count = fields.Integer(compute='_compute_hire_notice')
    hire_notice_missing = fields.Boolean(
        compute='_compute_hire_notice',
        help='Hiring order without a sent notice to the tax authority.')

    @api.depends('order_type', 'hire_notice_ids.state', 'employee_id',
                 'company_id.director_id')
    def _compute_hire_notice(self):
        Notice = self.env['hr.hire.notice']
        for order in self:
            notices = order.hire_notice_ids
            order.hire_notice_count = len(notices)
            order.hire_notice_missing = bool(
                order.order_type == 'hiring'
                and order.employee_id
                and order.state != 'cancelled'
                and not Notice._excluded_reason(order.employee_id, order.company_id)
                and not notices.filtered(
                    lambda n: n.notice_type == 'initial'
                    and n.state in ('sent', 'accepted')))

    def action_create_hire_notice(self):
        self.ensure_one()
        notice = self.env['hr.hire.notice'].create_from_order(self)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.hire.notice',
            'res_id': notice.id,
            'view_mode': 'form',
        }

    def action_view_hire_notices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'l10n_ua_hr_reports.action_hr_hire_notice')
        action['domain'] = [('order_id', '=', self.id)]
        action['context'] = {'default_order_id': self.id,
                             'default_employee_id': self.employee_id.id,
                             'default_company_id': self.company_id.id}
        return action
