"""Інформаційні запити до ДПС (через кабінет, з КЕП-підписом).

Наразі підтримано J1300205 «Запит про отримання витягу щодо стану розрахунків з
бюджетами та фондами». Модель наслідує l10n_ua.dps.submit.mixin, тож підпис і
подання — той самий універсальний потік, що й для декларацій/накладних.
Структуру XML звірено з офіційним XSD ДПС (tests/schemas/J1300205.xsd).
"""

import base64
import re
from datetime import date
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Реквізити форми запиту (fixed-значення з XSD ДПС).
REQUEST_FORMS = {
    'j1300205': {
        'c_doc': 'J13', 'c_doc_sub': '002', 'c_doc_ver': '5',
        'label': 'Стан розрахунків з бюджетом (витяг)',
    },
}
SOFTWARE = 'Odoo l10n_ua'


class L10nUaTaxRequest(models.Model):
    _name = 'l10n_ua.tax.request'
    _description = 'Інформаційний запит до ДПС'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    request_type = fields.Selection(
        selection=[('j1300205', 'Стан розрахунків з бюджетом (J1300205)')],
        string='Тип запиту', required=True, default='j1300205', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company)
    request_date = fields.Date(
        string='Дата запиту', required=True,
        default=fields.Date.context_today, tracking=True)
    state = fields.Selection(
        selection=[('draft', 'Чернетка'), ('generated', 'Сформовано'),
                   ('submitted', 'Подано')],
        default='draft', tracking=True, copy=False)
    submission_date = fields.Date(string='Дата подання', copy=False)
    xml_file = fields.Binary(string='XML-файл', attachment=True, copy=False)
    xml_filename = fields.Char(copy=False)
    response_receipt = fields.Text(string='Квитанція', readonly=True, copy=False)

    @api.depends('request_type', 'request_date')
    def _compute_name(self):
        labels = dict(self._fields['request_type'].selection)
        for rec in self:
            rec.name = '%s %s' % (
                labels.get(rec.request_type, _('Запит')), rec.request_date or '')

    # --- генерація XML ---

    def action_generate_xml(self):
        for rec in self:
            xml = rec._render_request_xml(rec._request_vals())
            rec.xml_file = base64.b64encode(xml.encode('windows-1251')).decode()
            form = REQUEST_FORMS[rec.request_type]
            edrpou = re.sub(r'\D', '', rec._request_edrpou(rec.company_id))
            rec.xml_filename = '%s%s%s_%s_%s.xml' % (
                form['c_doc'], form['c_doc_sub'], form['c_doc_ver'],
                edrpou, (rec.request_date or date.today()).strftime('%Y%m%d'))
            rec.state = 'generated'
        return True

    @staticmethod
    def _request_edrpou(company):
        """Код ЄДРПОУ компанії; `vat` — запасне джерело."""
        return company.edrpou or company.vat or ''

    def _request_vals(self):
        """Зібрати реквізити запиту (компанія + період). Відсутні обов'язкові —
        явний UserError (не підставляємо фейк у документ для ДПС)."""
        self.ensure_one()
        company = self.company_id
        edrpou = re.sub(r'\D', '', self._request_edrpou(company))
        office = company.tax_office_code or ''
        missing = []
        if not edrpou:
            missing.append(_('код ЄДРПОУ компанії'))
        if not office:
            missing.append(_('код ДПІ компанії (tax_office_code)'))
        if missing:
            raise UserError(_(
                'Для формування запиту заповніть: %s.') % ', '.join(missing))
        d = self.request_date or date.today()
        form = REQUEST_FORMS[self.request_type]
        return {
            'c_doc': form['c_doc'], 'c_doc_sub': form['c_doc_sub'],
            'c_doc_ver': form['c_doc_ver'],
            'tin': edrpou,
            'c_reg': int(office[:2]) if len(office) >= 2 else 0,
            'c_raj': int(office[2:4]) if len(office) >= 4 else 0,
            'period_month': d.month,
            'period_type': 1,
            'period_year': d.year,
            'c_sti_orig': office,
            'd_fill': d.strftime('%d%m%Y'),
            'hname': company.name or '',
        }

    @api.model
    def _render_request_xml(self, vals):
        """Стейтлес-рендер XML запиту (J1300205 v5), валідний за XSD ДПС.

        Кодування windows-1251. Порядок елементів звірено з J1300205.xsd
        (DHead: fixed J13/002/5, D_FILL/SOFTWARE; DBody: HFILL, HNAME, HTIN).
        """
        def esc(v):
            return escape(str(v or ''))

        return '\n'.join([
            '<?xml version="1.0" encoding="windows-1251"?>',
            '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xsi:noNamespaceSchemaLocation="%s%s%s.xsd">' % (
                vals['c_doc'], vals['c_doc_sub'], vals['c_doc_ver']),
            '    <DECLARHEAD>',
            '        <TIN>%s</TIN>' % esc(vals['tin']),
            '        <C_DOC>%s</C_DOC>' % vals['c_doc'],
            '        <C_DOC_SUB>%s</C_DOC_SUB>' % vals['c_doc_sub'],
            '        <C_DOC_VER>%s</C_DOC_VER>' % vals['c_doc_ver'],
            '        <C_DOC_TYPE>0</C_DOC_TYPE>',
            '        <C_DOC_CNT>1</C_DOC_CNT>',
            '        <C_REG>%s</C_REG>' % vals['c_reg'],
            '        <C_RAJ>%s</C_RAJ>' % vals['c_raj'],
            '        <PERIOD_MONTH>%s</PERIOD_MONTH>' % vals['period_month'],
            '        <PERIOD_TYPE>%s</PERIOD_TYPE>' % vals['period_type'],
            '        <PERIOD_YEAR>%s</PERIOD_YEAR>' % vals['period_year'],
            '        <C_STI_ORIG>%s</C_STI_ORIG>' % esc(vals['c_sti_orig']),
            '        <C_DOC_STAN>1</C_DOC_STAN>',
            '        <D_FILL>%s</D_FILL>' % vals['d_fill'],
            '        <SOFTWARE>%s</SOFTWARE>' % SOFTWARE,
            '    </DECLARHEAD>',
            '    <DECLARBODY>',
            '        <HFILL>%s</HFILL>' % vals['d_fill'],
            '        <HNAME>%s</HNAME>' % esc(vals['hname']),
            '        <HTIN>%s</HTIN>' % esc(vals['tin']),
            '    </DECLARBODY>',
            '</DECLAR>',
        ])

    # --- дії/стан ---

    def action_submit(self):
        """Відкрити КЕП-підпис і подання запиту до ДПС."""
        return self.action_kep_submit()

    def action_draft(self):
        self.write({'state': 'draft', 'submission_date': False})

    # --- контракт l10n_ua.dps.submit.mixin ---

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати запит до ДПС')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'submitted',
            'submission_date': fields.Date.context_today(self),
            'response_receipt': receipt,
        })
        self.message_post(body=_('Запит подано до ДПС. Квитанція: %s') % (receipt or '—'))
