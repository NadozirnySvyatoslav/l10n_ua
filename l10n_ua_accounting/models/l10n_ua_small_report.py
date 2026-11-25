"""Фінансова звітність малого підприємства (ф. № 1-м, № 2-м) і
мікропідприємства (ф. № 1-мс, № 2-мс) — НП(С)БО 25 «Спрощена фінансова
звітність» (наказ Мінфіну № 39 від 25.02.2000, ред. від 23.12.2025),
додатки 1 і 2. XML: J0901107 і J0901205.

The rows are not a second mapping of the chart of accounts: each one adds up
rows of the full Форма № 1 / № 2 of this module, following розділи II і III
of НП(С)БО 25:

* small: 1010 takes the investment property (п. 2.3), 1090 the deferred tax
  assets (п. 2.6), 1410 the revaluation capital (п. 2.18), 1425 the withdrawn
  capital (п. 2.21); 2240 — інші фінансові доходи й інші доходи (п. 5.3),
  2180 — адміністративні, збутові й інші операційні витрати (п. 5.5), 2270 —
  фінансові та інші витрати (п. 5.6);
* micro: 1010 takes the intangible assets, the unfinished capital investments
  and the long-term biological assets (п. 1.1 розд. III), 1090 the financial
  investments (п. 1.2), 1155 all current receivables (п. 1.4), 1190 the
  current financial investments (п. 1.6), 1400 the additional and the reserve
  capital (п. 1.7); 2160 and 2165 — all other incomes and expenses (пп. 2.2,
  2.4); 2310 is entered by hand (п. 2.7).

Amounts are in thousands of hryvnias with one decimal (DGdecimal1 of the
XSD), rounded half away from zero. The totals are added up from the rounded
rows, so that the form adds up as the controls of ДПС check it; the rounding
difference between the two sides of the balance goes to 1420 «Нерозподілений
прибуток», as the accountant would do by hand. ``balance_difference`` is the
difference of the ledger itself, before rounding.
"""

import base64
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

from .l10n_ua_balance_report import BALANCE_LINES, BALANCE_SUB_LINES
from .l10n_ua_pnl_report import pnl_complete

# Rows: (sequence, code, name, kind, spec)
#   section — title; bal — sum of Form 1 rows (codes); bal_sub — «у тому
#   числі», not in totals; cost — original cost: the parent row minus the wear
#   row of spec (parent, wear); finished — 1103 (account 26 within 1100);
#   pnl — sum of Form 2 detail keys; manual — entered by hand;
#   sum — [(sign, code), …] of rows of this form.
SMALL_BALANCE = [
    (10, '', 'I. Необоротні активи', 'section', None),
    (20, '1000', 'Нематеріальні активи', 'bal', ['1000']),
    (21, '1001', 'первісна вартість', 'bal_sub', ['1001']),
    (22, '1002', 'накопичена амортизація', 'bal_sub', ['1002']),
    (30, '1005', 'Незавершені капітальні інвестиції', 'bal', ['1005']),
    (40, '1010', 'Основні засоби', 'bal', ['1010', '1015']),
    (41, '1011', 'первісна вартість', 'cost', ('1010', '1012')),
    (42, '1012', 'знос', 'bal_sub', ['1012']),
    (50, '1020', 'Довгострокові біологічні активи', 'bal', ['1020']),
    (60, '1030', 'Довгострокові фінансові інвестиції', 'bal', ['1030', '1035']),
    (70, '1090', 'Інші необоротні активи', 'bal', ['1040', '1045', '1090']),
    (80, '1095', 'Усього за розділом I', 'sum',
     [(1, '1000'), (1, '1005'), (1, '1010'), (1, '1020'), (1, '1030'), (1, '1090')]),
    (90, '', 'II. Оборотні активи', 'section', None),
    (100, '1100', 'Запаси', 'bal', ['1100']),
    (101, '1103', 'у тому числі готова продукція', 'finished', None),
    (110, '1110', 'Поточні біологічні активи', 'bal', ['1110']),
    (120, '1125', 'Дебіторська заборгованість за товари, роботи, послуги', 'bal', ['1120', '1125']),
    (130, '1135', 'Дебіторська заборгованість за розрахунками з бюджетом', 'bal', ['1135']),
    (131, '1136', 'у тому числі з податку на прибуток', 'bal_sub', ['1136']),
    (140, '1155', 'Інша поточна дебіторська заборгованість', 'bal', ['1130', '1155']),
    (150, '1160', 'Поточні фінансові інвестиції', 'bal', ['1160']),
    (160, '1165', 'Гроші та їх еквіваленти', 'bal', ['1165']),
    (170, '1170', 'Витрати майбутніх періодів', 'bal', ['1170']),
    (180, '1190', 'Інші оборотні активи', 'bal', ['1190']),
    (190, '1195', 'Усього за розділом II', 'sum',
     [(1, c) for c in ('1100', '1110', '1125', '1135', '1155', '1160', '1165', '1170', '1190')]),
    (200, '1200', 'III. Необоротні активи, утримувані для продажу, та групи вибуття', 'bal', ['1200']),
    (210, '1300', 'Баланс', 'sum', [(1, '1095'), (1, '1195'), (1, '1200')]),
    (300, '', 'I. Власний капітал', 'section', None),
    (310, '1400', 'Зареєстрований (пайовий) капітал', 'bal', ['1400']),
    (320, '1410', 'Додатковий капітал', 'bal', ['1405', '1410']),
    (330, '1415', 'Резервний капітал', 'bal', ['1415']),
    (340, '1420', 'Нерозподілений прибуток (непокритий збиток)', 'bal', ['1420']),
    (350, '1425', 'Неоплачений капітал', 'bal', ['1425', '1430']),
    (360, '1495', 'Усього за розділом I', 'sum',
     [(1, c) for c in ('1400', '1410', '1415', '1420', '1425')]),
    (370, '1595', "II. Довгострокові зобов'язання, цільове фінансування та забезпечення", 'bal',
     ['1500', '1510', '1515', '1520', '1525']),
    (380, '', "III. Поточні зобов'язання", 'section', None),
    (390, '1600', 'Короткострокові кредити банків', 'bal', ['1600']),
    (400, '1610', "Поточна кредиторська заборгованість за довгостроковими зобов'язаннями", 'bal', ['1610']),
    (410, '1615', 'Поточна кредиторська заборгованість за товари, роботи, послуги', 'bal', ['1615']),
    (420, '1620', 'Поточна кредиторська заборгованість за розрахунками з бюджетом', 'bal', ['1620']),
    (421, '1621', 'у тому числі з податку на прибуток', 'bal_sub', ['1621']),
    (430, '1625', 'Поточна кредиторська заборгованість за розрахунками зі страхування', 'bal', ['1625']),
    (440, '1630', 'Поточна кредиторська заборгованість за розрахунками з оплати праці', 'bal', ['1630']),
    (450, '1665', 'Доходи майбутніх періодів', 'bal', ['1665']),
    (460, '1690', "Інші поточні зобов'язання", 'bal', ['1605', '1635', '1660', '1690']),
    (470, '1695', 'Усього за розділом III', 'sum',
     [(1, c) for c in ('1600', '1610', '1615', '1620', '1625', '1630', '1665', '1690')]),
    (480, '1700', "IV. Зобов'язання, пов'язані з необоротними активами, утримуваними для продажу, "
                  'та групами вибуття', 'bal', ['1700']),
    (490, '1900', 'Баланс', 'sum', [(1, '1495'), (1, '1595'), (1, '1695'), (1, '1700')]),
]

SMALL_PNL = [
    (510, '2000', 'Чистий дохід від реалізації продукції (товарів, робіт, послуг)', 'pnl', ['net_revenue']),
    (520, '2120', 'Інші операційні доходи', 'pnl', ['other_operating_income']),
    (530, '2240', 'Інші доходи', 'pnl', ['equity_income', 'financial_income', 'other_income']),
    (540, '2280', 'Разом доходи (2000 + 2120 + 2240)', 'sum', [(1, '2000'), (1, '2120'), (1, '2240')]),
    (550, '2050', 'Собівартість реалізованої продукції (товарів, робіт, послуг)', 'pnl', ['cost_of_sales']),
    (560, '2180', 'Інші операційні витрати', 'pnl',
     ['administrative_expenses', 'selling_expenses', 'other_operating_expenses']),
    (570, '2270', 'Інші витрати', 'pnl', ['financial_expenses', 'equity_losses', 'other_expenses']),
    (580, '2285', 'Разом витрати (2050 + 2180 + 2270)', 'sum', [(1, '2050'), (1, '2180'), (1, '2270')]),
    (590, '2290', 'Фінансовий результат до оподаткування (2280 - 2285)', 'sum', [(1, '2280'), (-1, '2285')]),
    (600, '2300', 'Податок на прибуток', 'pnl', ['income_tax_expense']),
    (610, '2350', 'Чистий прибуток (збиток) (2290 - 2300)', 'sum', [(1, '2290'), (-1, '2300')]),
]

MICRO_BALANCE = [
    (10, '', 'I. Необоротні активи', 'section', None),
    (40, '1010', 'Основні засоби', 'bal', ['1000', '1005', '1010', '1015', '1020']),
    (41, '1011', 'первісна вартість', 'cost', ('1010', '1012')),
    (42, '1012', 'знос', 'bal_sub', ['1002', '1012']),
    (70, '1090', 'Інші необоротні активи', 'bal', ['1030', '1035', '1040', '1045', '1090']),
    (80, '1095', 'Усього за розділом I', 'sum', [(1, '1010'), (1, '1090')]),
    (90, '', 'II. Оборотні активи', 'section', None),
    (100, '1100', 'Запаси', 'bal', ['1100', '1110']),
    (140, '1155', 'Поточна дебіторська заборгованість', 'bal', ['1120', '1125', '1130', '1135', '1155']),
    (160, '1165', 'Гроші та їх еквіваленти', 'bal', ['1165']),
    (180, '1190', 'Інші оборотні активи', 'bal', ['1160', '1170', '1190', '1200']),
    (190, '1195', 'Усього за розділом II', 'sum', [(1, c) for c in ('1100', '1155', '1165', '1190')]),
    (210, '1300', 'Баланс', 'sum', [(1, '1095'), (1, '1195')]),
    (300, '', 'I. Власний капітал', 'section', None),
    (310, '1400', 'Капітал', 'bal', ['1400', '1405', '1410', '1415']),
    (340, '1420', 'Нерозподілений прибуток (непокритий збиток)', 'bal', ['1420']),
    (350, '1425', 'Неоплачений капітал', 'bal', ['1425', '1430']),
    (360, '1495', 'Усього за розділом I', 'sum', [(1, '1400'), (1, '1420'), (1, '1425')]),
    (370, '1595', "II. Довгострокові зобов'язання, цільове фінансування та забезпечення", 'bal',
     ['1500', '1510', '1515', '1520', '1525']),
    (380, '', "III. Поточні зобов'язання", 'section', None),
    (390, '1600', 'Короткострокові кредити банків', 'bal', ['1600']),
    (410, '1615', 'Поточна кредиторська заборгованість за товари, роботи, послуги', 'bal', ['1615']),
    (420, '1620', 'Поточна кредиторська заборгованість за розрахунками з бюджетом', 'bal', ['1620']),
    (430, '1625', 'Поточна кредиторська заборгованість за розрахунками зі страхування', 'bal', ['1625']),
    (440, '1630', 'Поточна кредиторська заборгованість за розрахунками з оплати праці', 'bal', ['1630']),
    (460, '1690', "Інші поточні зобов'язання", 'bal', ['1605', '1610', '1635', '1660', '1665', '1690', '1700']),
    (470, '1695', 'Усього за розділом III', 'sum',
     [(1, c) for c in ('1600', '1615', '1620', '1625', '1630', '1690')]),
    (490, '1900', 'Баланс', 'sum', [(1, '1495'), (1, '1595'), (1, '1695')]),
]

MICRO_PNL = [
    (510, '2000', 'Чистий дохід від реалізації продукції (товарів, робіт, послуг)', 'pnl', ['net_revenue']),
    (520, '2160', 'Інші доходи', 'pnl',
     ['other_operating_income', 'equity_income', 'financial_income', 'other_income']),
    (540, '2280', 'Разом доходи (2000 + 2160)', 'sum', [(1, '2000'), (1, '2160')]),
    (550, '2050', 'Собівартість реалізованої продукції (товарів, робіт, послуг)', 'pnl', ['cost_of_sales']),
    (560, '2165', 'Інші витрати', 'pnl',
     ['administrative_expenses', 'selling_expenses', 'other_operating_expenses',
      'financial_expenses', 'equity_losses', 'other_expenses']),
    (580, '2285', 'Разом витрати (2050 + 2165)', 'sum', [(1, '2050'), (1, '2165')]),
    (590, '2290', 'Фінансовий результат до оподаткування (2280 - 2285)', 'sum', [(1, '2280'), (-1, '2285')]),
    (600, '2300', 'Податок на прибуток', 'pnl', ['income_tax_expense']),
    (605, '2310', 'Витрати (доходи), які зменшують (збільшують) фінансовий результат після '
                  'оподаткування', 'manual', None),
    (610, '2350', 'Чистий прибуток (збиток) (2290 - 2300 - (+) 2310)', 'sum',
     [(1, '2290'), (-1, '2300'), (-1, '2310')]),
]

SMALL_FORMS = {
    'small': (SMALL_BALANCE, SMALL_PNL, 'J0901107'),
    'micro': (MICRO_BALANCE, MICRO_PNL, 'J0901205'),
}
# Rows printed in parentheses (contra and expense rows)
PAREN_CODES = ('1002', '1012', '1425', '2050', '2180', '2270', '2285', '2300', '2165')


def to_thousands(amount, digits=1):
    """Hryvnias to thousands of hryvnias, rounded half away from zero."""
    return float_round((amount or 0.0) / 1000.0, precision_digits=digits,
                       rounding_method='HALF-UP')


def _round1(amount):
    return float_round(amount, precision_digits=1, rounding_method='HALF-UP')


# Seq below this are asset rows of the balance, the rest equity and liabilities
LIABILITY_SEQ = 300


class L10nUaSmallReport(models.Model):
    _name = 'l10n_ua.small.report'
    _description = 'Simplified Financial Statements (НП(С)БО 25)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    kind = fields.Selection(
        [('small', 'Small Enterprise (1-m, 2-m)'), ('micro', 'Micro Enterprise (1-ms, 2-ms)')],
        string='Kind', required=True, default='small', tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(
        string='Period Start', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
    )
    date_to = fields.Date(
        string='Period End', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=12, day=31),
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')], default='draft', tracking=True)
    line_ids = fields.One2many('l10n_ua.small.report.line', 'report_id', string='Lines')
    balance_line_ids = fields.One2many(
        'l10n_ua.small.report.line', 'report_id', string='Balance Lines',
        domain=[('part', '=', 'balance')])
    pnl_line_ids = fields.One2many(
        'l10n_ua.small.report.line', 'report_id', string='Income Statement Lines',
        domain=[('part', '=', 'pnl')])
    balance_difference = fields.Float(
        string='Assets − Liabilities (thous. UAH)', digits=(16, 1), readonly=True,
        help='Row 1300 minus row 1900 at the end of the period. Not zero when the '
             'ledger does not balance or a row of Form 1 has accounts without a row.')
    note = fields.Text(string='Notes')

    @api.depends('kind', 'date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            title = ('Фінансова звітність мікропідприємства' if rec.kind == 'micro'
                     else 'Фінансова звітність малого підприємства')
            period = ''
            if rec.date_from and rec.date_to:
                period = f' за {rec.date_from.strftime("%d.%m.%Y")} – {rec.date_to.strftime("%d.%m.%Y")}'
            rec.name = title + period

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_('The start of the period must not be after its end.'))

    def _form(self):
        self.ensure_one()
        return SMALL_FORMS[self.kind]

    # ── Actions ─────────────────────────────────────────────

    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Cannot recalculate a confirmed report. Set it back to draft first.'))
            rec.line_ids.unlink()
            rec._generate_lines()

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Calculate the report before confirming.'))
            rec.state = 'confirmed'

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_print(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_accounting.action_report_small').report_action(self)

    # ── Data ────────────────────────────────────────────────

    def _balance_rows(self, date):
        """{Form 1 code: amount} and the finished goods (26) at a date."""
        balance = self.env['l10n_ua.balance.report'].new({'company_id': self.company_id.id})
        amounts, _unmapped = balance._get_row_amounts(date)
        code_of = {line[1]: line[3] for line in BALANCE_LINES if line[3]}
        code_of.update({sub[1]: sub[3] for sub in BALANCE_SUB_LINES})
        rows = {code_of[key]: value for key, value in amounts.items() if key in code_of}
        finished = 0.0
        for account, _partner, value, key in balance._get_row_groups(date):
            code = account.with_company(self.company_id).code or ''
            if key == 'inventories' and code.startswith('26'):
                finished += value
        return rows, finished

    def _column(self, balance_date, date_from, date_to):
        """{code: amount in thousands} of one column, totals from the rounded rows."""
        balance_rows, finished = self._balance_rows(balance_date)
        pnl = self.env['l10n_ua.pnl.report'].new({'company_id': self.company_id.id})
        pnl_amounts = pnl_complete(pnl._period_amounts(date_from, date_to)) \
            if date_from and date_to else {}
        values = {}
        balance_lines, pnl_lines, _xml = self._form()
        for seq, code, name, kind, spec in balance_lines + pnl_lines:
            if kind in ('bal', 'bal_sub'):
                values[code] = to_thousands(sum(balance_rows.get(c, 0.0) for c in spec))
            elif kind == 'finished':
                values[code] = to_thousands(finished)
            elif kind == 'pnl':
                values[code] = to_thousands(sum(pnl_amounts.get(k, 0.0) for k in spec))
        self._complete(values, balance_lines + pnl_lines)
        # The rounding difference of the two sides goes to 1420
        rounding = _round1(values.get('1300', 0.0) - values.get('1900', 0.0))
        raw = sum(balance_rows.get(c, 0.0) * (1 if seq < LIABILITY_SEQ else -1)
                  for seq, code, name, kind, spec in balance_lines if kind == 'bal'
                  for c in spec)
        if rounding and abs(raw) < 50.0:
            values['1420'] = _round1(values.get('1420', 0.0) + rounding)
            self._complete(values, balance_lines)
        values['__ledger_difference'] = to_thousands(raw)
        return values

    @api.model
    def _complete(self, values, lines):
        for seq, code, name, kind, spec in lines:
            if kind == 'cost':
                parent, wear = spec
                values[code] = _round1(values.get(parent, 0.0) - values.get(wear, 0.0))
            elif kind == 'sum':
                values[code] = _round1(sum(sign * values.get(c, 0.0) for sign, c in spec))

    def _generate_lines(self):
        self.ensure_one()
        start = fields.Date.subtract(self.date_from, days=1)
        previous_from = fields.Date.subtract(self.date_from, years=1)
        previous_to = fields.Date.subtract(self.date_to, years=1)
        balance_lines, pnl_lines, _xml = self._form()
        # Balance: at the start of the year (g3) and at the end of the period (g4);
        # results: for the period (g3) and the same period of the previous year (g4)
        g3_balance = self._column(start, None, None)
        g4_balance = self._column(self.date_to, None, None)
        g3_pnl = self._column(self.date_to, self.date_from, self.date_to)
        g4_pnl = self._column(previous_to, previous_from, previous_to)
        vals_list = []
        for part, (g3, g4) in (('balance', (g3_balance, g4_balance)), ('pnl', (g3_pnl, g4_pnl))):
            lines = balance_lines if part == 'balance' else pnl_lines
            for seq, code, name, kind, spec in lines:
                vals_list.append({
                    'report_id': self.id,
                    'sequence': seq,
                    'part': part,
                    'code': code,
                    'name': name,
                    'kind': kind,
                    'amount_g3': g3.get(code, 0.0),
                    'amount_g4': g4.get(code, 0.0),
                })
        self.env['l10n_ua.small.report.line'].create(vals_list)
        self.balance_difference = g4_balance['__ledger_difference']

    def _recompute_totals(self):
        """After a row entered by hand (2310): the totals below it."""
        for rec in self:
            balance_lines, pnl_lines, _xml = rec._form()
            lines = {l.code: l for l in rec.line_ids if l.part == 'pnl'}
            for field in ('amount_g3', 'amount_g4'):
                values = {code: line[field] for code, line in lines.items()}
                for seq, code, name, kind, spec in pnl_lines:
                    if kind == 'sum':
                        values[code] = _round1(sum(sign * values.get(c, 0.0) for sign, c in spec))
                        lines[code].with_context(l10n_ua_small_no_recompute=True).write(
                            {field: values[code]})

    def _xml_values(self):
        """{'R1000G3': 12.3, …}: thousands with one decimal (DGdecimal1).

        Rows printed in parentheses are written as positive numbers.
        TODO(#78): confirm the sign against a real accepted J0901107.
        """
        self.ensure_one()
        values = {}
        for line in self.line_ids.filtered('code'):
            for field, graph in (('amount_g3', 3), ('amount_g4', 4)):
                amount = line[field]
                if line.code in PAREN_CODES:
                    amount = abs(amount)
                if amount:
                    values[f'R{line.code}G{graph}'] = round(amount, 1)
        return values


class L10nUaSmallReportLine(models.Model):
    _name = 'l10n_ua.small.report.line'
    _description = 'Simplified Financial Statements Line'
    _order = 'part, sequence, id'

    report_id = fields.Many2one('l10n_ua.small.report', required=True, ondelete='cascade')
    sequence = fields.Integer()
    part = fields.Selection([('balance', 'Balance'), ('pnl', 'Income Statement')], string='Part')
    code = fields.Char(string='Row Code')
    name = fields.Char(string='Line Name')
    kind = fields.Char(string='Kind')
    amount_g3 = fields.Float(string='Graph 3', digits=(16, 1))
    amount_g4 = fields.Float(string='Graph 4', digits=(16, 1))

    def write(self, vals):
        if not self.env.context.get('l10n_ua_small_no_recompute') and (
                'amount_g3' in vals or 'amount_g4' in vals):
            if self.filtered(lambda l: l.report_id.state != 'draft'):
                raise UserError(_('A confirmed report cannot be changed. Set it back to draft first.'))
            if self.filtered(lambda l: l.kind != 'manual'):
                raise UserError(_(
                    'Only row 2310 is entered by hand; the other rows come from the ledger. '
                    'Recalculate the report instead.'))
            res = super().write(vals)
            self.report_id._recompute_totals()
            return res
        return super().write(vals)
