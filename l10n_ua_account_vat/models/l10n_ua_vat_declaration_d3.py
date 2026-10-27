"""Додаток 3 (Д3, J0299826 / F0299826): заяви про повернення бюджетного відшкодування,
коштів з рахунку в СЕА ПДВ і врахування реєстраційної суми при реорганізації.

Розділи форми (наказ № 21 у редакції № 400) і теги XSD:

* підпункт «а» — відшкодування на рахунок у банку (рядок 20.2.1): R0303G2/R0303G3
  (період декларації), R0304G2 (сума), R0305G1S (IBAN), R0305G3S (банк);
* «Відомості щодо зміни реквізитів рахунку» — R0401G2/R0401G3 (період раніше
  поданої декларації), R0402G2S (новий IBAN), R0403G1S (банк);
* підпункт «б», таблиця 1 — відшкодування в рахунок інших платежів (рядок 20.2.2):
  T1RXXXXG2 (КБК), T1RXXXXG3S (рахунок у Казначействі), T1RXXXXG4 (сума), R05G4 (усього);
* таблиця 2 — кошти на рахунку в СЕА ПДВ: R06G1..R06G4 (г.4 = г.1 − г.2 − г.3, г.2 — рядок 18);
* таблиця 3 — перерахування надлишку СЕА на рахунок у банку: R07G1 (сума), R07G2S (банк),
  R07G3S (IBAN); R07G4 — у погашення податкового боргу з ПДВ (п. 87.1);
* заява платника, що реорганізується: R08G1 (ΣНакл), таблиця 4 T4RXXXXG2..G5S
  (правонаступник, частка ΣНакл, дата і номер передавального акта), R09G3 (усього);
* заява правонаступника: таблиця 5 T5RXXXXG2..G6S (реорганізований платник, ΣНакл на
  момент припинення, підтверджена ΣНакл, дата і номер акта/довідки), R010G4 (усього г.4).

Усі суми — цілі гривні (DGdecimal0). Розділи, крім «а»/«б», заповнюються вручну.
"""
import re
from xml.sax.saxutils import escape

from odoo import api, fields, models, _
from odoo.tools import float_round

from .l10n_ua_vat_declaration_xml import _int

IBAN_RE = re.compile(r'UA\d{27}')


def _iban(value):
    return re.sub(r'\s', '', value or '').upper()


def _r0(value):
    return float_round(value or 0.0, precision_digits=0)


class L10nUaVatDeclarationD3Offset(models.Model):
    _name = 'l10n_ua.vat.declaration.d3.offset'
    _description = 'Д3, таблиця 1: відшкодування в рахунок інших платежів'
    _order = 'sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    kbk = fields.Char(string='КБК', required=True, size=8,
                      help='Графа 2: код бюджетної класифікації платежу (8 цифр)')
    treasury_account = fields.Char(string='Рахунок у Казначействі', required=True,
                                   help='Графа 3: рахунок платежу в Казначействі')
    amount = fields.Monetary(string='Сума', currency_field='currency_id',
                             help='Графа 4, цілі гривні; разом = рядок 20.2.2')


class L10nUaVatDeclarationD3Reorg(models.Model):
    _name = 'l10n_ua.vat.declaration.d3.reorg'
    _description = 'Д3, таблиця 4: правонаступник платника, що реорганізується'
    _order = 'sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', string='Правонаступник')
    partner_ipn = fields.Char(string='ІПН правонаступника', required=True, help='Графа 2')
    amount = fields.Monetary(
        string='ΣНакл правонаступнику', currency_field='currency_id',
        help='Графа 3: сума ΣНакл, що включається до ΣНакл правонаступника згідно з часткою '
             'в передавальному акті / розподільчому балансі')
    act_date = fields.Date(string='Дата акта', required=True,
                           help='Графа 4: дата передавального акта / розподільчого балансу')
    act_number = fields.Char(string='Номер акта', required=True, help='Графа 5')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self:
            ipn = line.partner_id.ipn if 'ipn' in line.partner_id._fields else False
            if ipn:
                line.partner_ipn = ipn


class L10nUaVatDeclarationD3Predecessor(models.Model):
    _name = 'l10n_ua.vat.declaration.d3.predecessor'
    _description = 'Д3, таблиця 5: реорганізований платник (заява правонаступника)'
    _order = 'sequence, id'

    declaration_id = fields.Many2one(
        'l10n_ua.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', string='Реорганізований платник')
    partner_ipn = fields.Char(string='ІПН', required=True, help='Графа 2')
    amount_termination = fields.Monetary(
        string='ΣНакл на дату припинення', currency_field='currency_id',
        help='Графа 3: сума ΣНакл, сформована на момент державної реєстрації припинення')
    amount_confirmed = fields.Monetary(
        string='Підтверджена ΣНакл', currency_field='currency_id',
        help='Графа 4: реєстраційна сума, підтверджена документальною перевіркою')
    act_date = fields.Date(string='Дата акта/довідки', required=True, help='Графа 5')
    act_number = fields.Char(string='Номер акта/довідки', required=True, help='Графа 6')

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for line in self:
            ipn = line.partner_id.ipn if 'ipn' in line.partner_id._fields else False
            if ipn:
                line.partner_ipn = ipn


class L10nUaVatDeclarationD3(models.Model):
    _inherit = 'l10n_ua.vat.declaration'

    # Підпункт «а»: рахунок для відшкодування (рядок 20.2.1)
    d3_iban = fields.Char(
        string='Рахунок (IBAN)', compute='_compute_d3_bank', store=True, readonly=False,
        help='Д3, підпункт «а»: рахунок платника, на який перераховується відшкодування '
             '(рядок 20.2.1). За замовчуванням — перший банківський рахунок компанії.')
    d3_bank_name = fields.Char(
        string='Банк', compute='_compute_d3_bank', store=True, readonly=False,
        help='Найменування банку / небанківського надавача платіжних послуг')
    # Відомості щодо зміни реквізитів рахунку
    d3_change_month = fields.Integer(
        string='Місяць декларації', help='Д3, зміна реквізитів: звітний період раніше '
                                          'поданої декларації, відшкодування за якою '
                                          'перерахувати на новий рахунок')
    d3_change_year = fields.Integer(string='Рік декларації')
    d3_change_iban = fields.Char(string='Новий рахунок (IBAN)')
    d3_change_bank_name = fields.Char(string='Банк нового рахунку')
    # Підпункт «б», таблиця 1
    d3_offset_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d3.offset', 'declaration_id',
        string='Д3: у рахунок інших платежів', copy=False)
    # Таблиця 2: кошти на рахунку в СЕА ПДВ
    d3_sea_balance = fields.Monetary(
        string='Кошти на рахунку СЕА ПДВ', currency_field='currency_id',
        help='Д3, таблиця 2, графа 1: сума коштів на рахунку в СЕА ПДВ на момент подання '
             'декларації. Заповнюється лише якщо надлишок перераховується (таблиця 3).')
    d3_sea_tax_debt = fields.Monetary(
        string='Податковий борг з ПДВ', currency_field='currency_id',
        help='Д3, таблиця 2, графа 3: сума податкового боргу з ПДВ на момент подання')
    d3_sea_available = fields.Monetary(
        string='Може бути перераховано', currency_field='currency_id',
        compute='_compute_d3_sea_available',
        help='Д3, таблиця 2, графа 4 = графа 1 − рядок 18 − графа 3')
    # Таблиця 3 і п. 87.1
    d3_sea_refund_amount = fields.Monetary(
        string='Перерахувати на рахунок у банку', currency_field='currency_id',
        help='Д3, таблиця 3: сума надлишку СЕА, що перераховується на рахунок платника')
    d3_sea_refund_iban = fields.Char(
        string='Рахунок для коштів СЕА (IBAN)', compute='_compute_d3_bank', store=True,
        readonly=False)
    d3_sea_refund_bank_name = fields.Char(
        string='Банк для коштів СЕА', compute='_compute_d3_bank', store=True, readonly=False)
    d3_sea_debt_amount = fields.Monetary(
        string='У погашення податкового боргу з ПДВ', currency_field='currency_id',
        help='Д3: сума надлишку СЕА, що перераховується до бюджету в рахунок погашення '
             'податкового боргу з ПДВ (не більше графи 3 таблиці 2)')
    # Реорганізація
    d3_reorg_amount = fields.Monetary(
        string='ΣНакл, що передається правонаступникам', currency_field='currency_id',
        help='Д3, заява платника, що реорганізується (подається в останній декларації)')
    d3_reorg_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d3.reorg', 'declaration_id',
        string='Д3: правонаступники (таблиця 4)', copy=False)
    d3_predecessor_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d3.predecessor', 'declaration_id',
        string='Д3: реорганізовані платники (таблиця 5)', copy=False)

    @api.depends('company_id')
    def _compute_d3_bank(self):
        for rec in self:
            bank = rec.company_id.partner_id.bank_ids[:1]
            iban = _iban(bank.acc_number) or False
            bank_name = bank.bank_id.name or False
            rec.d3_iban = rec.d3_iban or iban
            rec.d3_bank_name = rec.d3_bank_name or bank_name
            rec.d3_sea_refund_iban = rec.d3_sea_refund_iban or iban
            rec.d3_sea_refund_bank_name = rec.d3_sea_refund_bank_name or bank_name

    @api.depends('d3_sea_balance', 'line_18_vat', 'd3_sea_tax_debt')
    def _compute_d3_sea_available(self):
        for rec in self:
            rec.d3_sea_available = (rec.d3_sea_balance or 0.0) - (rec.line_18_vat or 0.0) \
                - (rec.d3_sea_tax_debt or 0.0)

    # ------------------------------------------------------------------ дані

    def _d3_refund(self):
        return _r0(self.line_20_2_vat) > 0

    def _d3_account_change(self):
        return bool(self.d3_change_month or self.d3_change_year or self.d3_change_iban
                    or self.d3_change_bank_name)

    def _d3_sea(self):
        return bool(_r0(self.d3_sea_balance) or _r0(self.d3_sea_refund_amount)
                    or _r0(self.d3_sea_debt_amount))

    def _d3_reorg(self):
        return bool(_r0(self.d3_reorg_amount) or self.d3_reorg_line_ids)

    def _d3_needed(self):
        """Д3 обов'язковий при рядку 20.2 (п. 5 розд. V Порядку) і за будь-якої заяви."""
        self.ensure_one()
        return bool(self._d3_refund() or self.d3_offset_line_ids or self._d3_account_change()
                    or self._d3_sea() or self._d3_reorg() or self.d3_predecessor_line_ids)

    def _vat_attachments(self):
        res = super()._vat_attachments()
        if self._d3_needed():
            res.append(('d3', self._render_d3))
        return res

    # ------------------------------------------------------------------ перевірки

    def _vat_xml_problems(self):
        problems = super()._vat_xml_problems()
        if self._d3_needed():
            problems += self._d3_check()
        return problems

    def _d3_check(self):
        self.ensure_one()
        problems = []
        if _r0(self.line_20_2_1_vat) > 0:
            if not IBAN_RE.fullmatch(_iban(self.d3_iban)):
                problems.append(_('Д3: рахунок для відшкодування (рядок 20.2.1) — IBAN '
                                  'формату UA + 27 цифр'))
            if not (self.d3_bank_name or '').strip():
                problems.append(_('Д3: найменування банку для відшкодування (рядок 20.2.1)'))
        if self._d3_account_change():
            if not 1 <= (self.d3_change_month or 0) <= 12 or \
                    not 2000 <= (self.d3_change_year or 0) <= 2100:
                problems.append(_('Д3, зміна реквізитів рахунку: місяць і рік декларації'))
            if not IBAN_RE.fullmatch(_iban(self.d3_change_iban)):
                problems.append(_('Д3, зміна реквізитів рахунку: новий IBAN (UA + 27 цифр)'))
            if not (self.d3_change_bank_name or '').strip():
                problems.append(_('Д3, зміна реквізитів рахунку: найменування банку'))
        offsets = self.d3_offset_line_ids
        total = sum(_r0(l.amount) for l in offsets)
        if total != _r0(self.line_20_2_2_vat):
            problems.append(_('Д3, таблиця 1: «Усього» (%(t).0f) має дорівнювати рядку 20.2.2 '
                              '(%(r).0f)', t=total, r=_r0(self.line_20_2_2_vat)))
        bad = offsets.filtered(lambda l: not re.fullmatch(r'[1-9]\d{7}', l.kbk or '')
                               or not (l.treasury_account or '').strip()
                               or _r0(l.amount) <= 0)
        if bad:
            problems.append(_('Д3, таблиця 1: КБК (8 цифр), рахунок у Казначействі і сума '
                              'в рядках: %s') % ', '.join(l.kbk or '?' for l in bad[:5]))
        problems += self._d3_check_sea()
        problems += self._d3_check_reorg()
        return problems

    def _d3_check_sea(self):
        problems = []
        if not self._d3_sea():
            return problems
        refund, debt = _r0(self.d3_sea_refund_amount), _r0(self.d3_sea_debt_amount)
        available = _r0(self.d3_sea_available)
        if not _r0(self.d3_sea_balance):
            problems.append(_('Д3, таблиця 2: сума коштів на рахунку в СЕА ПДВ'))
        if available <= 0:
            problems.append(_('Д3, таблиця 2: кошти на рахунку в СЕА ПДВ не перевищують '
                              'суму до сплати (графа 4 = %.0f)') % available)
        if refund < 0 or debt < 0 or refund + debt > max(available, 0):
            problems.append(_('Д3: суми до перерахування з рахунку в СЕА ПДВ (%(s).0f) '
                              'перевищують графу 4 таблиці 2 (%(a).0f)',
                              s=refund + debt, a=available))
        if debt > _r0(self.d3_sea_tax_debt):
            problems.append(_('Д3: сума в погашення боргу не може перевищувати графу 3 '
                              'таблиці 2 (податковий борг)'))
        if not refund and not debt:
            problems.append(_('Д3, таблиця 2 заповнюється лише разом із рішенням про '
                              'перерахування коштів СЕА (таблиця 3 або погашення боргу)'))
        if refund:
            if not IBAN_RE.fullmatch(_iban(self.d3_sea_refund_iban)):
                problems.append(_('Д3, таблиця 3: рахунок (IBAN, UA + 27 цифр)'))
            if not (self.d3_sea_refund_bank_name or '').strip():
                problems.append(_('Д3, таблиця 3: найменування банку'))
        return problems

    def _d3_check_reorg(self):
        problems = []
        lines = self.d3_reorg_line_ids
        if self._d3_reorg():
            if not lines or _r0(self.d3_reorg_amount) <= 0:
                problems.append(_('Д3, заява платника, що реорганізується: ΣНакл і таблиця 4 '
                                  '(правонаступники)'))
            elif sum(_r0(l.amount) for l in lines) != _r0(self.d3_reorg_amount):
                problems.append(_('Д3, таблиця 4: «Усього» графи 3 має дорівнювати ΣНакл, '
                                  'що передається правонаступникам'))
        bad = lines.filtered(lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or '')
                             or not l.act_date or not (l.act_number or '').strip())
        bad5 = self.d3_predecessor_line_ids.filtered(
            lambda l: not re.fullmatch(r'\d{12}', l.partner_ipn or '')
            or not l.act_date or not (l.act_number or '').strip())
        if bad or bad5:
            problems.append(_('Д3, таблиці 4/5: ІПН (12 цифр), дата і номер акта в рядках: %s')
                            % ', '.join((l.partner_id.display_name or l.partner_ipn or '?')
                                        for l in [*bad, *bad5][:5]))
        return problems

    # ------------------------------------------------------------------ XML

    def _render_d3(self, head):
        """Д3 у порядку XSD J0299826 / F0299826."""
        self.ensure_one()
        body = [self._render_taxpayer(head)]

        def tag(name, value):
            body.append(f'<{name}>{value}</{name}>')

        if self._d3_refund():
            # «…визначене у декларації (рядок 20.2) за ____ 20__ року» — цей період.
            tag('R0303G2', head['period_month'])
            tag('R0303G3', head['period_year'])
        if _r0(self.line_20_2_1_vat) > 0:
            tag('R0304G2', _int(self.line_20_2_1_vat))
            tag('R0305G1S', _iban(self.d3_iban))
            tag('R0305G3S', escape(self.d3_bank_name.strip()))
        if self._d3_account_change():
            tag('R0401G2', self.d3_change_month)
            tag('R0401G3', self.d3_change_year)
            tag('R0402G2S', _iban(self.d3_change_iban))
            tag('R0403G1S', escape(self.d3_change_bank_name.strip()))

        def column(prefix, col, rows, fmt):
            return ''.join(f'<{prefix}RXXXXG{col} ROWNUM="{n}">{fmt(row)}</{prefix}RXXXXG{col}>'
                           for n, row in enumerate(rows, 1))

        offsets = self.d3_offset_line_ids.sorted(lambda l: (l.sequence, l.id))
        if offsets:
            body += [column('T1', '2', offsets, lambda r: r.kbk),
                     column('T1', '3S', offsets, lambda r: escape(r.treasury_account.strip())),
                     column('T1', '4', offsets, lambda r: _int(r.amount))]
            tag('R05G4', _int(sum(_r0(l.amount) for l in offsets)))
        if self._d3_sea():
            tag('R06G1', _int(self.d3_sea_balance))
            tag('R06G2', _int(self.line_18_vat))
            tag('R06G3', _int(self.d3_sea_tax_debt))
            tag('R06G4', _int(self.d3_sea_available))
            if _r0(self.d3_sea_refund_amount):
                tag('R07G1', _int(self.d3_sea_refund_amount))
                tag('R07G2S', escape(self.d3_sea_refund_bank_name.strip()))
                tag('R07G3S', _iban(self.d3_sea_refund_iban))
            if _r0(self.d3_sea_debt_amount):
                tag('R07G4', _int(self.d3_sea_debt_amount))
        reorg = self.d3_reorg_line_ids.sorted(lambda l: (l.sequence, l.id))
        if self._d3_reorg():
            tag('R08G1', _int(self.d3_reorg_amount))
        if reorg:
            body += [column('T4', '2', reorg, lambda r: r.partner_ipn),
                     column('T4', '3', reorg, lambda r: _int(r.amount)),
                     column('T4', '4D', reorg, lambda r: r.act_date.strftime('%d%m%Y')),
                     column('T4', '5S', reorg, lambda r: escape(r.act_number.strip()))]
            tag('R09G3', _int(sum(_r0(l.amount) for l in reorg)))
        pred = self.d3_predecessor_line_ids.sorted(lambda l: (l.sequence, l.id))
        if pred:
            body += [column('T5', '2', pred, lambda r: r.partner_ipn),
                     column('T5', '3', pred, lambda r: _int(r.amount_termination)),
                     column('T5', '4', pred, lambda r: _int(r.amount_confirmed)),
                     column('T5', '5D', pred, lambda r: r.act_date.strftime('%d%m%Y')),
                     column('T5', '6S', pred, lambda r: escape(r.act_number.strip()))]
            tag('R010G4', _int(sum(_r0(l.amount_confirmed) for l in pred)))
        body.append(self._render_signers())
        return self._wrap(self._vat_form('d3'), self._render_head(head), ''.join(body))
