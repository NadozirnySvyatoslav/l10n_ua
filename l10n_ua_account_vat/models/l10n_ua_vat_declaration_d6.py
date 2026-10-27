"""Додаток 6 (Д6, J0215826 / F0215826): заява із скаргою на контрагента.

Заява про допущення продавцем помилок в обов'язкових реквізитах ПН та/або
порушення продавцем/покупцем граничних термінів реєстрації ПН/РК в ЄРПН
(п. 201.10 ПКУ; Порядок № 21, розд. III п. 16 — там ще стара нумерація «Д7»).

Рядки таблиці заповнює бухгалтер вручну; документ можна вибрати з податкових
накладних — тоді підставляються контрагент, дата, номер і суми. Графа 6 (номер)
не заповнюється, якщо номера немає (відмова продавця надати / зареєструвати ПН).
До заяви додаються копії документів — кількість аркушів (HEXPL).
"""
import re
from xml.sax.saxutils import escape

from odoo import api, fields, models, _

from .l10n_ua_vat_declaration_xml import _dec2


class L10nUaVatDeclarationD6Line(models.Model):
    _name = 'l10n_ua.vat.declaration.d6.line'
    _description = 'Д6: рядок заяви із скаргою на контрагента'
    _order = 'sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    doc_kind = fields.Selection(
        [('pn', 'Податкова накладна'), ('rk', 'Розрахунок коригування')],
        string='Документ', required=True, default='pn', help='Графа 2')
    tax_invoice_id = fields.Many2one(
        'l10n_ua.tax.invoice', string='ПН / РК',
        domain="[('company_id', '=', company_id)]",
        help='Необов\'язково: документ з обліку — заповнює графи 2–8')
    partner_id = fields.Many2one('res.partner', string='Контрагент')
    partner_name = fields.Char(
        string='Найменування', required=True,
        help='Графа 3: платник, на якого подається скарга (продавець / покупець)')
    partner_ipn = fields.Char(string='ІПН', required=True, help='Графа 4')
    doc_date = fields.Date(string='Дата', required=True, help='Графа 5')
    doc_number = fields.Char(
        string='Номер', help='Графа 6: не заповнюється, якщо номер ПН / РК невідомий')
    base_amount = fields.Monetary(
        string='Обсяг без ПДВ', currency_field='currency_id',
        help='Графа 7: обсяг поставки / коригування без ПДВ, грн')
    vat_amount = fields.Monetary(
        string='Сума ПДВ', currency_field='currency_id',
        help='Графа 8: сума ПДВ / коригування ПЗ і ПК, грн (+/-)')
    description = fields.Text(
        string='Опис помилки / порушення', required=True,
        help='Графа 9: опис помилок в обов\'язкових реквізитах ПН та/або порушення '
             'граничних термінів реєстрації ПН / РК в ЄРПН')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self.filtered('partner_id'):
            line.partner_name = line.partner_id.commercial_partner_id.name
            ipn = line.partner_id.ipn if 'ipn' in line.partner_id._fields else False
            if ipn:
                line.partner_ipn = ipn

    @api.onchange('tax_invoice_id')
    def _onchange_tax_invoice_id(self):
        for line in self.filtered('tax_invoice_id'):
            invoice = line.tax_invoice_id
            line.doc_kind = invoice.doc_type
            line.partner_id = invoice.partner_id
            line._onchange_partner_id()
            line.doc_date = invoice.date
            line.doc_number = invoice.number
            line.base_amount = invoice.total_base
            line.vat_amount = invoice.total_vat


class L10nUaVatDeclarationD6(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    d6_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d6.line', 'declaration_id',
        string='Д6: скарги на контрагентів', copy=False)
    d6_attached_sheets = fields.Integer(
        string='Додано копій документів, арк.',
        help='Д6: кількість аркушів копій документів, що підтверджують сплату ПДВ або '
             'отримання товарів/послуг')

    def _vat_attachments(self):
        res = super()._vat_attachments()
        if self.d6_line_ids:
            res.append(('d6', self._render_d6))
        return res

    def _vat_xml_problems(self):
        problems = super()._vat_xml_problems()
        problems += self._d6_check()
        return problems

    def _d6_check(self):
        self.ensure_one()
        problems = []
        lines = self.d6_line_ids
        if not lines:
            return problems
        bad_ipn = lines.filtered(lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or ''))
        if bad_ipn:
            problems.append(_('Д6: ІПН контрагента (12 цифр): %s')
                            % ', '.join(l.partner_name or '?' for l in bad_ipn[:5]))
        for label, missing in (
                (_('найменування контрагента'), lines.filtered(
                    lambda l: not (l.partner_name or '').strip())),
                (_('дата документа'), lines.filtered(lambda l: not l.doc_date)),
                (_('опис помилки / порушення'), lines.filtered(
                    lambda l: not (l.description or '').strip()))):
            if missing:
                problems.append(_('Д6: %(what)s у рядках: %(rows)s', what=label, rows=', '.join(
                    str(lines.ids.index(l.id) + 1) for l in missing[:10])))
        if self.d6_attached_sheets < 0:
            problems.append(_('Д6: кількість аркушів додатків не може бути від\'ємною'))
        return problems

    def _render_d6(self, head):
        """Д6: таблиця (графи 2–9) і кількість аркушів додатків."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]
        rows = self.d6_line_ids.sorted(lambda l: (l.sequence, l.id))
        kinds = dict(self.env['l10n_ua.vat.declaration.d6.line']._fields['doc_kind']
                     ._description_selection(self.env))

        def column(col, fmt, skip_empty=False):
            return ''.join(f'<T1RXXXXG{col} ROWNUM="{n}">{fmt(row)}</T1RXXXXG{col}>'
                           for n, row in enumerate(rows, 1)
                           if not skip_empty or fmt(row))

        body += [
            column('2S', lambda r: escape(kinds[r.doc_kind])),
            column('3S', lambda r: escape(r.partner_name.strip())),
            column('4', lambda r: r.partner_ipn),
            column('5D', lambda r: r.doc_date.strftime('%d%m%Y')),
            # Графа 6 порожня, якщо номера немає — такі рядки просто пропускаємо.
            column('6S', lambda r: escape((r.doc_number or '').strip()), skip_empty=True),
            column('7', lambda r: _dec2(r.base_amount)),
            column('8', lambda r: _dec2(r.vat_amount)),
            column('9S', lambda r: escape(' '.join(r.description.split()))),
        ]
        if self.d6_attached_sheets > 0:
            body.append(f'<HEXPL>{self.d6_attached_sheets}</HEXPL>')
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d6'), self._render_head(head), ''.join(body))
