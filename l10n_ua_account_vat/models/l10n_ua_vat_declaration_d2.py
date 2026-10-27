"""Додаток 2 (Д2), таблиця 1: розшифровка від'ємного значення (рядок 19).

Рядки — за періодом виникнення, постачальником і періодом складання документа.
Сума рядка «Усього» графи 6 дорівнює рядку 19, графи 10 — рядку 21 (Порядок № 21,
розд. V п. 5). Розподіл, який робить ``_fill_d2_lines``:

* залишок минулого періоду (рядок 16.1) переходить рядками Д2 попередньої
  декларації зі своїми періодами й постачальниками; якщо цього періоду від'ємне
  значення зменшилось, погашаються спершу найстаріші суми;
* нова частина (рядок 19 понад 16.1) припадає на податковий кредит цього періоду —
  на найпізніші отримані ПН, кожна в межах свого ПДВ; імпорт і решта (зменшення
  зобов'язань) — на власний ІПН платника.

Рядки можна виправити вручну до формування XML.
"""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import float_compare, float_round


def _r2(value):
    return float_round(value or 0.0, precision_digits=2)


class L10nUaVatDeclarationD2Line(models.Model):
    _name = 'l10n_ua.vat.declaration.d2.line'
    _description = "Д2: рядок розшифровки від'ємного значення"
    _order = 'origin_year, origin_month, doc_year, doc_month, sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    origin_month = fields.Integer(string='Місяць виникнення', required=True,
                                  help='Графа 2: звітний період виникнення від\'ємного значення')
    origin_year = fields.Integer(string='Рік виникнення', required=True, help='Графа 3')
    partner_id = fields.Many2one('res.partner', string='Постачальник')
    partner_ipn = fields.Char(string='ІПН', required=True,
                              help='Графа 4: ІПН постачальника або власний ІПН (імпорт, '
                                   'зменшення податкових зобов\'язань)')
    doc_month = fields.Integer(string='Місяць документа', required=True,
                               help='Графа 5: період складання ПН / РК / митної декларації')
    doc_year = fields.Integer(string='Рік документа', required=True)
    amount = fields.Monetary(string="Від'ємне значення", currency_field='currency_id',
                             help='Графа 6')
    carry_amount = fields.Monetary(
        string='До ПК наступного періоду', currency_field='currency_id',
        compute='_compute_carry_amount', store=True, readonly=False,
        help='Графа 10. Без погашення боргу й відшкодування дорівнює графі 6')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self:
            ipn = line.partner_id.ipn if 'ipn' in line.partner_id._fields else False
            if ipn:
                line.partner_ipn = ipn

    @api.depends('amount')
    def _compute_carry_amount(self):
        for line in self:
            line.carry_amount = line.amount


class L10nUaVatDeclarationD2(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    def _own_ipn(self):
        return self.company_id.l10n_ua_vat_ipn or ''

    def _d2_carried_rows(self):
        """Залишок з минулого періоду: рядки Д2 попередньої декларації (графа 10)."""
        self.ensure_one()
        previous = self._previous_declaration()
        rows = [{
            'origin_month': l.origin_month, 'origin_year': l.origin_year,
            'partner_id': l.partner_id.id, 'partner_ipn': l.partner_ipn,
            'doc_month': l.doc_month, 'doc_year': l.doc_year, 'amount': l.carry_amount,
        } for l in previous.d2_line_ids if l.carry_amount > 0]
        missing = _r2(self.line_16_1_vat - sum(r['amount'] for r in rows))
        if missing > 0:
            # Попередня декларація без Д2 (наприклад, подана не з Odoo): залишок
            # показуємо одним рядком на власний ІПН — бухгалтер уточнить вручну.
            end = (previous.period_id.date_end if previous
                   else fields.Date.subtract(self.period_id.date_start, days=1))
            rows.insert(0, {
                'origin_month': end.month, 'origin_year': end.year, 'partner_id': False,
                'partner_ipn': self._own_ipn(), 'doc_month': end.month,
                'doc_year': end.year, 'amount': missing,
            })
        elif missing < 0:
            # Рядок 16.1 менший за суму рядків (ручна правка) — гасимо найстаріші.
            self._d2_consume(rows, -missing)
        return rows

    @staticmethod
    def _d2_consume(rows, amount):
        """Погасити ``amount`` з найстаріших рядків (FIFO)."""
        rows.sort(key=lambda r: (r['origin_year'], r['origin_month'],
                                 r['doc_year'], r['doc_month']))
        for row in rows:
            if amount <= 0:
                break
            used = min(row['amount'], amount)
            row['amount'] = _r2(row['amount'] - used)
            amount = _r2(amount - used)
        rows[:] = [r for r in rows if r['amount'] > 0]

    def _d2_current_sources(self):
        """Податковий кредит цього періоду за постачальником і періодом документа.

        Повертає список, найпізніші документи першими: (дата, ipn, partner_id,
        місяць, рік, ПДВ).
        """
        self.ensure_one()
        groups = defaultdict(lambda: [None, 0.0])
        own = self._own_ipn()
        for line in self.register_received_id.line_ids:
            if line.vat_amount <= 0:
                continue
            invoice = line.tax_invoice_id
            if invoice.is_import:
                ipn, partner = own, False
            else:
                ipn, partner = line.partner_ipn, line.partner_id.id
            doc_date = line.invoice_date or line.date
            key = (ipn, partner, doc_date.month, doc_date.year)
            group = groups[key]
            group[0] = max(group[0] or line.date, line.date)
            group[1] += line.vat_amount
        return sorted(((g[0], *key, g[1]) for key, g in groups.items()),
                      key=lambda s: s[0], reverse=True)

    def _fill_d2_lines(self):
        """Заповнити таблицю 1 Д2 за рядком 19 (див. опис модуля)."""
        self.ensure_one()
        self.d2_line_ids.unlink()
        negative = self.line_19_vat
        if float_compare(negative, 0.0, precision_digits=2) <= 0:
            return
        rows = self._d2_carried_rows()
        carried = sum(r['amount'] for r in rows)
        if carried > negative:
            self._d2_consume(rows, _r2(carried - negative))
        new_part = _r2(negative - sum(r['amount'] for r in rows))
        period_end = self.period_id.date_end
        current = defaultdict(float)
        for _date, ipn, partner, month, year, vat in self._d2_current_sources():
            if new_part <= 0:
                break
            part = min(_r2(vat), new_part)
            current[(ipn, partner, month, year)] += part
            new_part = _r2(new_part - part)
        if new_part > 0:
            current[(self._own_ipn(), False, period_end.month, period_end.year)] += new_part
        for (ipn, partner, month, year), amount in current.items():
            rows.append({
                'origin_month': period_end.month, 'origin_year': period_end.year,
                'partner_id': partner, 'partner_ipn': ipn,
                'doc_month': month, 'doc_year': year, 'amount': _r2(amount),
            })
        self.write({'d2_line_ids': [(0, 0, dict(r, sequence=i)) for i, r in enumerate(rows)]})

    def _d2_check(self):
        """Помилки в Д2 (для ``_check_vat_xml_ready``)."""
        self.ensure_one()
        problems = []
        if float_compare(self.line_19_vat, 0.0, precision_digits=2) <= 0:
            return problems
        lines = self.d2_line_ids
        if not lines:
            problems.append(_('Д2 не заповнено — натисніть «Розрахувати»'))
            return problems
        total = sum(lines.mapped('amount'))
        if float_round(total, precision_digits=0) != float_round(self.line_19_vat,
                                                                 precision_digits=0):
            problems.append(_('Д2: сума графи 6 (%(d2).2f) не дорівнює рядку 19 (%(r19).0f)',
                              d2=total, r19=self.line_19_vat))
        carry = sum(lines.mapped('carry_amount'))
        if float_round(carry, precision_digits=0) != float_round(self.line_21_vat,
                                                                 precision_digits=0):
            problems.append(_('Д2: сума графи 10 (%(d2).2f) не дорівнює рядку 21 (%(r21).0f)',
                              d2=carry, r21=self.line_21_vat))
        bad = lines.filtered(lambda l: not (l.partner_ipn or '').isdigit()
                             or len(l.partner_ipn) != 12
                             or not 1 <= l.origin_month <= 12 or not 1 <= l.doc_month <= 12)
        if bad:
            problems.append(_('Д2: ІПН (12 цифр) і місяці в рядках: %s')
                            % ', '.join((l.partner_id.display_name or l.partner_ipn or '?')
                                        for l in bad[:5]))
        return problems
