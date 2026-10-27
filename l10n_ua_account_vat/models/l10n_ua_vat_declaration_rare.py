"""Рідкісні таблиці декларації з ПДВ — вводяться вручну.

* Д1, таблиця 1.3 — РК РЕЗ 2 / РЕЗ 3 за операціями експорту окремих видів товарів
  (п.п. «б», «в» п.п. 97.4 підр. 2 розд. XX ПКУ) → рядки 7.2.2 (основна ставка) і
  7.2.3 (14 %).
* Д2, таблиця 1.1 — розшифровка відшкодування, що виникло з коригувань РЕЗ (ІПН
  300000000000 у графі 4 таблиці 1).
* Д2, таблиці 2 і 3 — перенесення від'ємного значення при реорганізації (п. 198.7 ПКУ):
  заява платника, що реорганізується (у декларації за останній період), і
  правонаступника (після підтвердження перевіркою; сума — у рядку 16.3).
"""
from odoo import api, fields, models, _

from .l10n_ua_vat_declaration_xml import _dec2, _int


class L10nUaVatDeclarationD1T13(models.Model):
    _name = 'l10n_ua.vat.declaration.d1.t13.line'
    _description = 'Д1, таблиця 1.3: коригування за експортом окремих видів товарів'
    _order = 'rk_date, id'

    declaration_id = fields.Many2one('l10n_ua.vat.declaration', required=True,
                                     ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    rk_date = fields.Date(string='Дата РК', required=True)
    rk_number = fields.Char(string='Номер РК', required=True)
    basis = fields.Selection([('1', '1 — РЕЗ 2 (п.п. «б» п.п. 97.4)'),
                              ('2', '2 — РЕЗ 3 (п.п. «в» п.п. 97.4)')],
                             string='Ознака', required=True, default='1')
    pn_date = fields.Date(string='Дата ПН', required=True)
    pn_number = fields.Char(string='Номер ПН', required=True)
    export_month = fields.Integer(string='Місяць експорту', required=True)
    export_year = fields.Integer(string='Рік експорту', required=True)
    base_amount = fields.Monetary(string='Коригування обсягу', currency_field='currency_id',
                                  help='Графа 9 — лише для РК РЕЗ 2')
    vat_20 = fields.Monetary(string='ПДВ, основна ставка', currency_field='currency_id')
    vat_14 = fields.Monetary(string='ПДВ, 14 %', currency_field='currency_id')


class L10nUaVatDeclarationD2Rez(models.Model):
    _name = 'l10n_ua.vat.declaration.d2.rez.line'
    _description = 'Д2, таблиця 1.1: відшкодування з коригувань РЕЗ'
    _order = 'credit_year, credit_month, id'

    declaration_id = fields.Many2one('l10n_ua.vat.declaration', required=True,
                                     ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    partner_ipn = fields.Char(string='ІПН постачальника', required=True,
                              help='300000000000 — якщо ПДВ сплачено до бюджету самим платником')
    credit_month = fields.Integer(string='Місяць включення до ПК', required=True)
    credit_year = fields.Integer(string='Рік включення до ПК', required=True)
    paid_month = fields.Integer(string='Місяць сплати', required=True)
    paid_year = fields.Integer(string='Рік сплати', required=True)
    amount = fields.Monetary(string='Фактично сплачено ПДВ', currency_field='currency_id')


class L10nUaVatDeclarationD2Reorg(models.Model):
    _name = 'l10n_ua.vat.declaration.d2.reorg.line'
    _description = "Д2, таблиці 2/3: від'ємне значення при реорганізації"
    _order = 'kind, id'

    declaration_id = fields.Many2one('l10n_ua.vat.declaration', required=True,
                                     ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    kind = fields.Selection([('out', 'Табл. 2 — передаю правонаступнику'),
                             ('in', 'Табл. 3 — отримую від реорганізованого')],
                            string='Таблиця', required=True, default='out')
    partner_ipn = fields.Char(string='ІПН правонаступника / реорганізованого', required=True)
    amount = fields.Monetary(string="Сума від'ємного значення", currency_field='currency_id')
    apply_month = fields.Integer(string='Місяць заяви реорганізованого',
                                 help='Табл. 3, графа 4: період, у якому подано заяву')
    apply_year = fields.Integer(string='Рік заяви реорганізованого')
    confirmed_amount = fields.Monetary(string='Підтверджено перевіркою',
                                       currency_field='currency_id', help='Табл. 3, графа 5')
    act_date = fields.Date(string='Дата акта / балансу', required=True)
    act_number = fields.Char(string='Номер акта / балансу', required=True)


class L10nUaVatDeclarationRare(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    d1_t13_line_ids = fields.One2many('l10n_ua.vat.declaration.d1.t13.line', 'declaration_id',
                                      string='Д1, таблиця 1.3', copy=False)
    d2_rez_line_ids = fields.One2many('l10n_ua.vat.declaration.d2.rez.line', 'declaration_id',
                                      string='Д2, таблиця 1.1', copy=False)
    d2_reorg_line_ids = fields.One2many('l10n_ua.vat.declaration.d2.reorg.line',
                                        'declaration_id', string='Д2, таблиці 2/3', copy=False)
    line_7_2_2_base = fields.Monetary(string='р.7.2.2 Коригування обсягу (основна ставка)',
                                      currency_field='currency_id',
                                      compute='_compute_rez_rows', store=True)
    line_7_2_2_vat = fields.Monetary(string='р.7.2.2 Коригування ПЗ (основна ставка)',
                                     currency_field='currency_id',
                                     compute='_compute_rez_rows', store=True)
    line_7_2_3_base = fields.Monetary(string='р.7.2.3 Коригування обсягу (14 %)',
                                      currency_field='currency_id',
                                      compute='_compute_rez_rows', store=True)
    line_7_2_3_vat = fields.Monetary(string='р.7.2.3 Коригування ПЗ (14 %)',
                                     currency_field='currency_id',
                                     compute='_compute_rez_rows', store=True)

    @api.depends('d1_t13_line_ids.base_amount', 'd1_t13_line_ids.vat_20',
                 'd1_t13_line_ids.vat_14')
    def _compute_rez_rows(self):
        for rec in self:
            lines = rec.d1_t13_line_ids
            rec.line_7_2_2_vat = round(sum(lines.mapped('vat_20')))
            rec.line_7_2_3_vat = round(sum(lines.mapped('vat_14')))
            rec.line_7_2_2_base = round(sum(lines.filtered('vat_20').mapped('base_amount')))
            rec.line_7_2_3_base = round(sum((lines - lines.filtered('vat_20'))
                                            .mapped('base_amount')))

    def _d1_has_extra(self):
        return bool(self.d1_t13_line_ids) or super()._d1_has_extra()

    def _d2_has_extra(self):
        return bool(self.d2_rez_line_ids or self.d2_reorg_line_ids) or super()._d2_has_extra()

    def _vat_xml_problems(self):
        problems = super()._vat_xml_problems()
        for line in self.d1_t13_line_ids:
            if not 1 <= line.export_month <= 12:
                problems.append(_('Д1 табл. 1.3: місяць експорту в РК %s') % line.rk_number)
            if line.basis == '2' and line.base_amount:
                problems.append(_('Д1 табл. 1.3: для РК РЕЗ 3 (%s) графа 9 не заповнюється')
                                % line.rk_number)
        rez_ipn = '300000000000'
        rez_refund = sum(self.d2_line_ids.filtered(
            lambda l: l.partner_ipn == rez_ipn).mapped('refund_amount'))
        if round(sum(self.d2_rez_line_ids.mapped('amount'))) != round(rez_refund):
            problems.append(_('Д2 табл. 1.1: «Усього» має дорівнювати графі 9 таблиці 1 для '
                              'ІПН 300000000000 (%.2f)') % rez_refund)
        for line in [*self.d2_rez_line_ids, *self.d2_reorg_line_ids]:
            if not (line.partner_ipn or '').isdigit() or len(line.partner_ipn) != 12:
                problems.append(_('Д2: ІПН %s має бути 12 цифр') % (line.partner_ipn or '?'))
        for line in self.d2_reorg_line_ids.filtered(lambda l: l.kind == 'in'):
            if not (1 <= line.apply_month <= 12 and line.apply_year):
                problems.append(_('Д2 табл. 3: період заяви реорганізованого (%s)')
                                % line.partner_ipn)
        return problems

    def _render_d1_extra(self):
        res = super()._render_d1_extra()
        rows = self.d1_t13_line_ids
        if not rows:
            return res

        def column(col, fmt, only=None):
            return ''.join(f'<T13RXXXXG{col} ROWNUM="{n}">{fmt(r)}</T13RXXXXG{col}>'
                           for n, r in enumerate(rows, 1) if only is None or only(r))

        return res + ''.join([
            column('2D', lambda r: r.rk_date.strftime('%d%m%Y')),
            column('3S', lambda r: r.rk_number),
            column('4', lambda r: r.basis),
            column('5D', lambda r: r.pn_date.strftime('%d%m%Y')),
            column('6S', lambda r: r.pn_number),
            column('7', lambda r: r.export_month),
            column('8', lambda r: r.export_year),
            column('9', lambda r: _dec2(r.base_amount), only=lambda r: r.basis == '1'),
            column('10', lambda r: _dec2(r.vat_20)),
            column('11', lambda r: _dec2(r.vat_14)),
            f'<R013G9>{_int(sum(rows.mapped("base_amount")))}</R013G9>',
            f'<R013G10>{_int(sum(rows.mapped("vat_20")))}</R013G10>',
            f'<R013G11>{_int(sum(rows.mapped("vat_14")))}</R013G11>',
        ])

    def _render_d2_extra(self):
        res = super()._render_d2_extra()
        body = []

        def column(prefix, col, rows, fmt):
            return ''.join(f'<{prefix}RXXXXG{col} ROWNUM="{n}">{fmt(r)}</{prefix}RXXXXG{col}>'
                           for n, r in enumerate(rows, 1))

        rez = self.d2_rez_line_ids
        if rez:
            body += [column('T11', '2', rez, lambda r: r.partner_ipn),
                     column('T11', '3', rez, lambda r: r.credit_month),
                     column('T11', '4', rez, lambda r: r.credit_year),
                     column('T11', '5', rez, lambda r: r.paid_month),
                     column('T11', '6', rez, lambda r: r.paid_year),
                     column('T11', '7', rez, lambda r: _dec2(r.amount)),
                     f'<R011G7>{_int(sum(rez.mapped("amount")))}</R011G7>']
        out = self.d2_reorg_line_ids.filtered(lambda l: l.kind == 'out')
        if out:
            total = sum(out.mapped('amount'))
            body += [f'<R03G2>{_int(total)}</R03G2>',
                     column('T2', '2', out, lambda r: r.partner_ipn),
                     column('T2', '3', out, lambda r: _dec2(r.amount)),
                     column('T2', '4D', out, lambda r: r.act_date.strftime('%d%m%Y')),
                     column('T2', '5S', out, lambda r: r.act_number),
                     f'<R04G3>{_int(total)}</R04G3>']
        inc = self.d2_reorg_line_ids.filtered(lambda l: l.kind == 'in')
        if inc:
            body += [column('T3', '2', inc, lambda r: r.partner_ipn),
                     column('T3', '3', inc, lambda r: _dec2(r.amount)),
                     column('T3', '4A', inc, lambda r: r.apply_month),
                     column('T3', '4B', inc, lambda r: r.apply_year),
                     column('T3', '5', inc, lambda r: _dec2(r.confirmed_amount)),
                     column('T3', '6D', inc, lambda r: r.act_date.strftime('%d%m%Y')),
                     column('T3', '7S', inc, lambda r: r.act_number),
                     f'<R05G5>{_int(sum(inc.mapped("confirmed_amount")))}</R05G5>']
        return res + ''.join(body)
