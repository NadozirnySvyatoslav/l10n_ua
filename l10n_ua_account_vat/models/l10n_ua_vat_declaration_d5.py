"""Додаток 5 (Д5, J0215726 / F0215726): частка використання в оподатковуваних операціях.

Таблиця 1 — частка за ст. 199 ПКУ: рядок 1 (п. 199.2/199.4) рахується в декларації за
грудень з обсягів постачання всіх декларацій року, рядок 2 (п. 199.3) — у періоді, коли
неоподатковувані операції задекларовано вперше, з обсягів цього періоду. Склад обсягів —
за підписами граф бланка: загальний = рядки 1.1–1.3, 2.1, 2.2, 2.3.x, 3, 5, 7.1, 7.2.x
колонки А; оподатковувані — ті самі без 2.2 і 5.
Таблиця 2 — РК річного перерахунку до ПН за п. 199.1 (ознака на РК), з реєстру виданих.
Таблиця 3 — розподіл ПДВ за касовим методом і загальними правилами (п. 15 розд. III
Порядку), вводиться вручну; графи 13–14 рахуються за формулами бланка.
"""
from odoo import api, fields, models, _
from odoo.tools import float_round

from .l10n_ua_vat_declaration_xml import _dec2, _int

TOTAL_FIELDS = ('line_1_1_base', 'line_1_2_base', 'line_1_3_base', 'line_2_base',
                'line_2_2_base', 'line_3_base', 'line_5_base', 'line_7_1_base')
TAXABLE_FIELDS = ('line_1_1_base', 'line_1_2_base', 'line_1_3_base', 'line_2_base',
                  'line_3_base', 'line_7_1_base')
T3_LABELS = [
    'Залишок неоплачених з попередніх періодів (касовий метод): обсяг',
    'Залишок неоплачених з попередніх періодів (касовий метод): ПДВ',
    'Придбання оплачені: обсяг', 'Придбання оплачені: ПДВ',
    'Придбання неоплачені: обсяг', 'Придбання неоплачені: ПДВ',
    'з них для касового методу: обсяг', 'з них для касового методу: ПДВ',
    'з них не для касового методу: обсяг', 'з них не для касового методу: ПДВ',
    'Оплата із залишку попередніх періодів: обсяг',
    'Оплата із залишку попередніх періодів: ПДВ',
    'Залишок, що переноситься: обсяг (гр.1 − гр.11 + гр.7)',
    'Залишок, що переноситься: ПДВ (гр.2 − гр.12 + гр.8)',
]


class L10nUaVatDeclarationD5(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    d5_share_mode = fields.Selection(
        selection=[
            ('annual', 'Рядок 1: річний розрахунок / перерахунок (п. 199.2, 199.4)'),
            ('first', 'Рядок 2: перший період неоподатковуваних операцій (п. 199.3)'),
        ],
        string='Д5: розрахунок частки',
        help='Порожньо — таблиця 1 Д5 не подається. Річний розрахунок — у декларації за '
             'грудень; при розрахунку декларації за грудень з неоподатковуваними '
             'операціями за рік вмикається сам.',
    )
    d5_total_volume = fields.Monetary(
        string='Д5: загальний обсяг постачання', currency_field='currency_id',
        compute='_compute_d5_share', store=True, readonly=False)
    d5_taxable_volume = fields.Monetary(
        string='Д5: оподатковувані операції', currency_field='currency_id',
        compute='_compute_d5_share', store=True, readonly=False)
    d5_taxable_share = fields.Float(
        string='Д5: частка в оподатковуваних, %', digits=(5, 2),
        compute='_compute_d5_percent', store=True)
    for _n, _label in enumerate(T3_LABELS[:12], 1):
        locals()[f'd5_t3_g{_n}'] = fields.Monetary(
            string=f'Д5 т.3 гр.{_n}: {_label}', currency_field='currency_id')
    del _n, _label
    d5_t3_g13 = fields.Monetary(string=f'Д5 т.3 гр.13: {T3_LABELS[12]}',
                                currency_field='currency_id', compute='_compute_d5_t3')
    d5_t3_g14 = fields.Monetary(string=f'Д5 т.3 гр.14: {T3_LABELS[13]}',
                                currency_field='currency_id', compute='_compute_d5_t3')

    @api.depends('d5_t3_g1', 'd5_t3_g11', 'd5_t3_g7', 'd5_t3_g2', 'd5_t3_g12', 'd5_t3_g8')
    def _compute_d5_t3(self):
        for rec in self:
            rec.d5_t3_g13 = rec.d5_t3_g1 - rec.d5_t3_g11 + rec.d5_t3_g7
            rec.d5_t3_g14 = rec.d5_t3_g2 - rec.d5_t3_g12 + rec.d5_t3_g8

    @api.depends('d5_share_mode', 'period_id', *TOTAL_FIELDS)
    def _compute_d5_share(self):
        for rec in self:
            sources = rec._d5_share_sources()
            rec.d5_total_volume = sum(sum(d[f] for f in TOTAL_FIELDS) for d in sources)
            rec.d5_taxable_volume = sum(sum(d[f] for f in TAXABLE_FIELDS) for d in sources)

    @api.depends('d5_total_volume', 'd5_taxable_volume')
    def _compute_d5_percent(self):
        for rec in self:
            rec.d5_taxable_share = (
                float_round(rec.d5_taxable_volume * 100.0 / rec.d5_total_volume,
                            precision_digits=2)
                if rec.d5_total_volume else 0.0)

    def _d5_share_sources(self):
        """Декларації, з обсягів яких рахується частка."""
        self.ensure_one()
        if self.d5_share_mode == 'first' or not self.d5_share_mode:
            return self if self.d5_share_mode else self.browse()
        end = self.period_id.date_end
        if not end:
            return self
        year = self.search([
            ('company_id', '=', self.company_id.id),
            ('period_id.date_end', '>=', end.replace(month=1, day=1)),
            ('period_id.date_end', '<=', end),
            ('state', 'in', ('calculated', 'submitted', 'accepted')),
            ('id', '!=', self._origin.id or self.id),
        ])
        return year | self

    def _calculate_from_registers(self):
        res = super()._calculate_from_registers()
        end = self.period_id.date_end
        if not self.d5_share_mode and end and end.month == 12:
            self.d5_share_mode = 'annual'
            if not any(d.line_5_base or d.line_2_2_base for d in self._d5_share_sources()):
                self.d5_share_mode = False
        return res

    def _d5_recalc_lines(self):
        """Таблиця 2: видані РК річного перерахунку частки."""
        self.ensure_one()
        return self.register_issued_id.line_ids.filtered(
            lambda l: l.doc_type == 'rk' and l.tax_invoice_id.vat_199_recalc
        ).sorted(lambda l: (l.date, l.id))

    def _d5_has_t3(self):
        return any(self[f'd5_t3_g{n}'] for n in range(1, 13))

    def _d5_needed(self):
        return bool(self.d5_share_mode or self._d5_recalc_lines() or self._d5_has_t3())

    def _vat_attachments(self):
        result = super()._vat_attachments()
        if self._d5_needed():
            result.append(('d5', self._render_d5))
        return result

    def _vat_xml_problems(self):
        problems = super()._vat_xml_problems()
        if self.d5_share_mode and self.d5_total_volume <= 0:
            problems.append(_('Д5: загальний обсяг постачання для розрахунку частки нульовий'))
        if self.d5_taxable_volume > self.d5_total_volume:
            problems.append(_('Д5: оподатковувані операції більші за загальний обсяг'))
        for line in self._d5_recalc_lines():
            if not line.tax_invoice_id.original_invoice_id:
                problems.append(_('Д5: РК %s не має ПН, до якої складено (за п. 199.1)')
                                % line.tax_invoice_id.display_name)
        return problems

    def _render_d5(self, head):
        self.ensure_one()
        body = [self._render_taxpayer(head)]
        if self.d5_share_mode:
            row = 'R011' if self.d5_share_mode == 'annual' else 'R012'
            share = self.d5_taxable_share
            body += [f'<{row}G4>{_int(self.d5_total_volume)}</{row}G4>',
                     f'<{row}G5>{_int(self.d5_taxable_volume)}</{row}G5>',
                     f'<{row}G6>{_dec2(share)}</{row}G6>',
                     f'<{row}G7>{_dec2(100.0 - share)}</{row}G7>']
        lines = self._d5_recalc_lines()
        if lines:
            def column(col, fmt):
                return ''.join(f'<T2RXXXXG{col} ROWNUM="{n}">{fmt(line)}</T2RXXXXG{col}>'
                               for n, line in enumerate(lines, 1))

            def original(line):
                return line.tax_invoice_id.original_invoice_id

            amounts = [('6', 'base_20'), ('7', 'base_7'), ('8', 'base_14'),
                       ('9', 'vat_20'), ('10', 'vat_7'), ('11', 'vat_14')]
            body += [
                column('2D', lambda l: original(l).date.strftime('%d%m%Y')),
                column('3S', lambda l: original(l).number or original(l).name or ''),
                column('4D', lambda l: (l.invoice_date or l.date).strftime('%d%m%Y')),
                column('5S', lambda l: l.invoice_number or l.tax_invoice_id.number or ''),
            ]
            for col, field in amounts:
                body.append(column(col, lambda l, f=field: _dec2(l[f])))
            for col, field in amounts:
                body.append(f'<R02G{col}>{_int(sum(lines.mapped(field)))}</R02G{col}>')
        if self._d5_has_t3():
            for n in range(1, 15):
                body.append(f'<R041G{n}>{_int(self[f"d5_t3_g{n}"])}</R041G{n}>')
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d5'), self._render_head(head), ''.join(body))
