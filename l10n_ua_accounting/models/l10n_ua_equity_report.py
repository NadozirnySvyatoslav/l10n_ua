"""Звіт про власний капітал (Форма № 4) — persistent stored report.

Rows and columns are those of Додаток 1 до НП(С)БО 1 (наказ Мінфіну № 73 від
07.02.2013, z0336-13, ред. від 23.12.2025); the additional articles 4111–4116,
4215–4225, 4280 and 4291 are those of Додаток 3 and are printed only when they
hold an amount, as in Форма № 1. The XML elements of J0901005 (ДПС, C_DOC_VER 5)
are named after the same codes and columns: R4000G3 … R4300G10.

Each column is a group of equity accounts of the Інструкція № 291:

    3 Зареєстрований (пайовий) капітал   40
    4 Капітал у дооцінках                41
    5 Додатковий капітал                 42
    6 Резервний капітал                  43
    7 Нерозподілений прибуток            44, and 7, 8, 9 not yet closed
                                         (as row 1420 of Форма № 1)
    8 Неоплачений капітал                46
    9 Вилучений капітал                  45
   10 Всього                             sum of 3–9

An amount is credit − debit, so 45 and 46 (contra accounts) come out negative,
as in Форма № 1. Row 4000 is the balance before the period, row 4300 the
balance at its end; the rows between take each journal item of the period on
an equity account, by the account on the other side of its entry
(``EQUITY_RULES``). Classes 7–9 are the result of the period: an income or an
expense goes to 4100, and the closing of 79 to 44 does not change column 7.
Whatever no rule takes goes to 4290 «Інші зміни в капіталі», so 4300 always
equals the balance of the ledger.

The rows «Коригування» (4005 зміна облікової політики, 4010 виправлення
помилок, 4090 інші зміни) cannot be told apart from other entries on 44: they
are filled in by hand. A correction of a past period is posted in the current
one (44 against the account corrected), and no rule takes such an entry, so it
is in 4290: what is entered in a row «Коригування» is taken out of 4290 of the
same graph, and 4300 still equals the ledger. ``ledger_difference`` shows any
mismatch that remains.
"""

import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .l10n_ua_balance_report import BALANCE_LINES, BALANCE_SUB_LINES, balance_round
from .l10n_ua_fin_rounding import format_units, round_units, to_thousands
from .l10n_ua_pnl_report import PNL_LINES, pnl_complete


# Rows of Form 1 that are the balances of the columns
EQUITY_FORM1_ROWS = {
    'registered': '1400', 'revaluation': '1405', 'additional': '1410', 'reserve': '1415',
    'retained': '1420', 'unpaid': '1425', 'withdrawn': '1430',
}

# Columns: (field, graph, account prefixes)
EQUITY_COLUMNS = [
    ('registered', 3, ('40',)),
    ('revaluation', 4, ('41',)),
    ('additional', 5, ('42',)),
    ('reserve', 6, ('43',)),
    ('retained', 7, ('44', '7', '8', '9')),
    ('unpaid', 8, ('46',)),
    ('withdrawn', 9, ('45',)),
]
EQUITY_FIELDS = [col[0] for col in EQUITY_COLUMNS]
RESULT_PREFIXES = ('7', '8', '9')

# Rows: (sequence, code, name, line_type, parent code)
# line_type: header (group title without a code), detail, manual (filled in
# by hand), sub (a part of the parent row, not in the totals), opening,
# subtotal (4095), total (4295), closing (4300).
EQUITY_LINES = [
    (10, '4000', 'Залишок на початок року', 'opening', ''),
    (15, '', 'Коригування:', 'header', ''),
    (20, '4005', 'Зміна облікової політики', 'manual', ''),
    (30, '4010', 'Виправлення помилок', 'manual', ''),
    (40, '4090', 'Інші зміни', 'manual', ''),
    (50, '4095', 'Скоригований залишок на початок року', 'subtotal', ''),
    (60, '4100', 'Чистий прибуток (збиток) за звітний період', 'detail', ''),
    (70, '4110', 'Інший сукупний дохід за звітний період', 'detail', ''),
    (71, '4111', 'Дооцінка (уцінка) необоротних активів', 'sub', '4110'),
    (72, '4112', 'Дооцінка (уцінка) фінансових інструментів', 'sub', '4110'),
    (73, '4113', 'Накопичені курсові різниці', 'sub', '4110'),
    (74, '4114', 'Частка іншого сукупного доходу асоційованих і спільних підприємств', 'sub', '4110'),
    (76, '4116', 'Інший сукупний дохід', 'sub', '4110'),
    (80, '', 'Розподіл прибутку:', 'header', ''),
    (90, '4200', 'Виплати власникам (дивіденди)', 'detail', ''),
    (100, '4205', 'Спрямування прибутку до зареєстрованого капіталу', 'detail', ''),
    (110, '4210', 'Відрахування до резервного капіталу', 'detail', ''),
    (115, '4215', 'Сума чистого прибутку, належна до бюджету відповідно до законодавства', 'detail', ''),
    (120, '4220', 'Сума чистого прибутку на створення спеціальних (цільових) фондів', 'detail', ''),
    (125, '4225', 'Сума чистого прибутку на матеріальне заохочення', 'detail', ''),
    (130, '', 'Внески учасників:', 'header', ''),
    (140, '4240', 'Внески до капіталу', 'detail', ''),
    (150, '4245', 'Погашення заборгованості з капіталу', 'detail', ''),
    (160, '', 'Вилучення капіталу:', 'header', ''),
    (170, '4260', 'Викуп акцій (часток)', 'detail', ''),
    (180, '4265', 'Перепродаж викуплених акцій (часток)', 'detail', ''),
    (190, '4270', 'Анулювання викуплених акцій (часток)', 'detail', ''),
    (200, '4275', 'Вилучення частки в капіталі', 'detail', ''),
    (205, '4280', 'Зменшення номінальної вартості акцій', 'detail', ''),
    (210, '4290', 'Інші зміни в капіталі', 'detail', ''),
    (211, '4291', 'Придбання (продаж) неконтрольованої частки в дочірньому підприємстві', 'sub', '4290'),
    (220, '4295', 'Разом змін у капіталі', 'total', ''),
    (230, '4300', 'Залишок на кінець року', 'closing', ''),
]

# Additional articles (Додаток 3 до НП(С)БО 1): printed only with an amount.
EQUITY_ADDITIONAL_CODES = ('4111', '4112', '4113', '4114', '4116', '4215',
                           '4220', '4225', '4280', '4291')
EQUITY_MANUAL_CODES = ('4005', '4010', '4090')
# Rows added up in 4295: the movements of the period, not their parts.
EQUITY_CHANGE_CODES = tuple(
    line[1] for line in EQUITY_LINES if line[3] == 'detail')

# Journal items of the period: (column, counterpart account prefixes, row).
# The first rule of the item's column whose prefix matches an account on the
# other side of the entry wins; '' matches any. Prefixes follow the
# Інструкція № 291 and the Методичні рекомендації щодо заповнення форм
# фінансової звітності (наказ Мінфіну № 433 від 28.03.2013, розд. V).
EQUITY_RULES = [
    # Нерозподілений прибуток: classes 7–9 and their closing are the result
    ('retained', RESULT_PREFIXES, '4100'),
    ('retained', ('671',), '4200'),     # дивіденди нараховані
    ('retained', ('40',), '4205'),      # прибуток до зареєстрованого капіталу
    ('retained', ('43',), '4210'),      # до резервного капіталу
    ('retained', ('64',), '4215'),      # частина прибутку до бюджету (держпідприємства)
    ('retained', ('663',), '4225'),     # матеріальне заохочення
    ('retained', ('47', '48'), '4220'),  # спеціальні (цільові) фонди
    # Зареєстрований капітал
    ('registered', ('46',), '4240'),    # оголошений капітал, неоплачена частина
    ('registered', ('44',), '4205'),
    ('registered', ('45',), '4270'),    # анулювання викуплених часток
    ('registered', ('672',), '4275'),   # вилучення частки учасником
    ('registered', ('30', '31', '33', '37', '10', '11', '12', '15', '20', '22', '28'), '4240'),
    # Неоплачений капітал: the debt for the capital, paid in money or in kind
    ('unpaid', ('40', '42'), '4240'),
    ('unpaid', ('',), '4245'),
    # Вилучений капітал
    ('withdrawn', ('40',), '4270'),
    # Капітал у дооцінках
    ('revaluation', ('10', '11', '12', '13', '15', '16'), '4111'),
    ('revaluation', ('14', '35'), '4112'),
    ('revaluation', ('44',), '4290'),   # реалізований дооцінений капітал
    ('revaluation', ('',), '4116'),
    # Додатковий капітал: емісійний дохід, внески понад зареєстрований капітал
    ('additional', ('46', '30', '31', '33', '37'), '4240'),
    # Резервний капітал
    ('reserve', ('44',), '4210'),
]


def equity_column(code):
    """The column field of an account, or None: the longest prefix wins."""
    best, best_len = None, 0
    for field, _graph, prefixes in EQUITY_COLUMNS:
        for prefix in prefixes:
            if code.startswith(prefix) and len(prefix) > best_len:
                best, best_len = field, len(prefix)
    return best


def equity_row(column, code, counterpart_codes, amount):
    """The row a journal item on an equity account goes to.

    :param column: column field of the item's account
    :param code: the item's account code
    :param counterpart_codes: account codes on the other side of the entry
    :param amount: credit − debit of the item
    """
    if column == 'retained' and code.startswith(RESULT_PREFIXES):
        return '4100'
    # Between 43 and 44 only an increase of the reserve is «відрахування»;
    # covering a loss from the reserve is another change of the capital.
    if (column, amount > 0) in (('reserve', False), ('retained', True)) and any(
            c.startswith('44' if column == 'reserve' else '43') for c in counterpart_codes):
        return '4290'
    if column == 'withdrawn' and not any(c.startswith('40') for c in counterpart_codes):
        # Викуп збільшує вилучений капітал (дебет 45), перепродаж зменшує (кредит 45)
        return '4260' if amount < 0 else '4265'
    for rule_column, prefixes, row in EQUITY_RULES:
        if rule_column != column:
            continue
        for prefix in prefixes:
            if prefix == '' and counterpart_codes:
                return row
            if prefix and any(c.startswith(prefix) for c in counterpart_codes):
                return row
    return '4290'


class L10nUaEquityReport(models.Model):
    _name = 'l10n_ua.equity.report'
    _description = 'Statement of Changes in Equity (Form No.4)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    date_from = fields.Date(
        string='Period Start', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
    )
    date_to = fields.Date(
        string='Period End', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).replace(month=12, day=31),
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')],
        string='State', default='draft', tracking=True,
    )
    line_ids = fields.One2many('l10n_ua.equity.report.line', 'report_id', string='Lines')
    total_opening = fields.Monetary(
        string='Equity at Period Start', compute='_compute_totals', store=True,
        currency_field='currency_id',
    )
    total_closing = fields.Monetary(
        string='Equity at Period End', compute='_compute_totals', store=True,
        currency_field='currency_id',
    )
    ledger_difference = fields.Char(
        string='Difference with the Ledger', readonly=True,
        help='Columns whose balance at the end of the period (row 4300) differs '
             'from the balance of their accounts in the ledger. It appears when '
             'an amount is entered in the rows «Коригування» and not taken out '
             'of the row the entry went to.',
    )
    note = fields.Text(string='Notes')

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from.year == rec.date_to.year \
                    and (rec.date_from.month, rec.date_from.day) == (1, 1) \
                    and (rec.date_to.month, rec.date_to.day) == (12, 31):
                rec.name = f'Звіт про власний капітал за {rec.date_to.year} рік'
            else:
                rec.name = 'Звіт про власний капітал за %s – %s' % (
                    rec.date_from.strftime('%d.%m.%Y') if rec.date_from else '',
                    rec.date_to.strftime('%d.%m.%Y') if rec.date_to else '')

    @api.depends('line_ids.total', 'line_ids.code')
    def _compute_totals(self):
        for rec in self:
            by_code = {line.code: line for line in rec.line_ids}
            rec.total_opening = by_code['4000'].total if '4000' in by_code else 0.0
            rec.total_closing = by_code['4300'].total if '4300' in by_code else 0.0

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_('The start of the period must not be after its end.'))

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
        return self.env.ref('l10n_ua_accounting.action_report_equity').report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Run: pip install xlsxwriter'))
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_equity_xlsx(workbook)
        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': f'Ф4_власний_капітал_{self.date_to.strftime("%d.%m.%Y")}.xlsx',
            'type': 'binary',
            'raw': output.getvalue(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ── Data ────────────────────────────────────────────────

    def _equity_domain(self):
        return [('parent_state', '=', 'posted'), ('company_id', '=', self.company_id.id)]

    def _column_balances(self, domain):
        """credit − debit per column of the journal items of ``domain``."""
        amounts = dict.fromkeys(EQUITY_FIELDS, 0.0)
        MoveLine = self.env['account.move.line'].with_company(self.company_id)
        for account, balance in MoveLine._read_group(
                domain + self._equity_domain(), ['account_id'], ['balance:sum']):
            column = equity_column(account.with_company(self.company_id).code or '')
            if column:
                amounts[column] -= balance
        return amounts

    def _period_movements(self):
        """{row code: {column: amount}} of the journal items of the period."""
        self.ensure_one()
        company = self.company_id
        MoveLine = self.env['account.move.line'].with_company(company)
        lines = MoveLine.search(self._equity_domain() + [
            ('date', '>=', self.date_from), ('date', '<=', self.date_to)])
        codes = {account: account.with_company(company).code or '' for account in lines.account_id}
        equity_lines = lines.filtered(lambda l: equity_column(codes[l.account_id]))
        by_move = {}
        for line in equity_lines:
            by_move.setdefault(line.move_id, []).append(line)
        movements = {}
        for move, move_equity_lines in by_move.items():
            move_codes = [(other, other.account_id.with_company(company).code or '')
                          for other in move.line_ids]
            for line in move_equity_lines:
                code = codes[line.account_id]
                column = equity_column(code)
                amount = -line.balance
                # The accounts on the other side of the entry; an entry within
                # one column (e.g. 44 → 44) has none but its result accounts.
                counterparts = [
                    other_code for other, other_code in move_codes
                    if other != line
                    and (equity_column(other_code) != column or column == 'retained')
                    and (other.balance > 0) != (line.balance > 0)
                ]
                row = equity_row(column, code, counterparts, amount)
                cell = movements.setdefault(row, dict.fromkeys(EQUITY_FIELDS, 0.0))
                cell[column] += amount
        return movements

    def _generate_lines(self):
        self.ensure_one()
        opening = self._column_balances([('date', '<', self.date_from)])
        closing = self._column_balances([('date', '<=', self.date_to)])
        movements = self._period_movements()
        currency = self.company_id.currency_id
        vals_list = []
        for seq, code, name, line_type, parent in EQUITY_LINES:
            if line_type == 'opening':
                amounts = opening
            elif line_type in ('detail', 'sub'):
                amounts = movements.get(code, {})
            else:
                amounts = {}
            if code in EQUITY_ADDITIONAL_CODES and all(
                    currency.is_zero(amounts.get(f, 0.0)) for f in EQUITY_FIELDS):
                continue
            vals = {
                'report_id': self.id,
                'sequence': seq,
                'code': code,
                'name': name,
                'line_type': line_type,
                'parent_code': parent,
            }
            vals.update({f: amounts.get(f, 0.0) for f in EQUITY_FIELDS})
            vals_list.append(vals)
        self.env['l10n_ua.equity.report.line'].create(vals_list)
        # 4110 is the sum of its parts
        oci = self.line_ids.filtered(lambda l: l.code == '4110')
        parts = self.line_ids.filtered(lambda l: l.parent_code == '4110')
        oci.with_context(l10n_ua_equity_no_recompute=True).write(
            {f: sum(parts.mapped(f)) for f in EQUITY_FIELDS})
        self._recompute_totals(closing)

    def _recompute_totals(self, ledger_closing=None):
        """Fill 4095, 4295 and 4300 from the other rows and compare 4300 with
        the ledger."""
        for rec in self:
            by_code = {line.code: line for line in rec.line_ids if line.code}

            def total(codes, field):
                return sum(by_code[c][field] for c in codes if c in by_code)

            values = {}
            for field in EQUITY_FIELDS:
                adjusted = total(('4000',) + EQUITY_MANUAL_CODES, field)
                change = total(EQUITY_CHANGE_CODES, field)
                values[field] = (adjusted, change, adjusted + change)
            for code, index in (('4095', 0), ('4295', 1), ('4300', 2)):
                if code in by_code:
                    by_code[code].with_context(l10n_ua_equity_no_recompute=True).write(
                        {f: values[f][index] for f in EQUITY_FIELDS})
            closing = ledger_closing or rec._column_balances([('date', '<=', rec.date_to)])
            currency = rec.company_id.currency_id
            graphs = dict((col[0], col[1]) for col in EQUITY_COLUMNS)
            differences = [
                _('graph %(graph)s: %(amount)s',
                  graph=graphs[f], amount=currency.format(values[f][2] - closing[f]))
                for f in EQUITY_FIELDS
                if not currency.is_zero(values[f][2] - closing[f])
            ]
            rec.ledger_difference = ', '.join(differences) or False

    def _form1_column(self, date):
        """Form 1 rounded as it is printed (``balance_round``) at a date."""
        balance = self.env['l10n_ua.balance.report'].new({'company_id': self.company_id.id})
        amounts, _unmapped = balance._get_row_amounts(date)
        code_of = {line[1]: line[3] for line in BALANCE_LINES if line[3]}
        code_of.update({sub[1]: sub[3] for sub in BALANCE_SUB_LINES})
        return balance_round({code_of[k]: v for k, v in amounts.items() if k in code_of})

    def _net_profit_thousands(self):
        """Net result of Form 2 for the period, as Form 2 prints it."""
        pnl = self.env['l10n_ua.pnl.report'].new({'company_id': self.company_id.id})
        amounts = pnl._period_amounts(self.date_from, self.date_to)
        detail_keys = {line[1] for line in PNL_LINES if line[4] == 'detail'}
        return round_units(pnl_complete(
            {k: to_thousands(v) for k, v in amounts.items() if k in detail_keys})['net_profit'])

    def _form_values(self):
        """{code: {column: amount}} in thousands of hryvnias without decimals.

        The movements are rounded row by row. The balances 4000 and 4300 are
        those of Form 1 (rows 1400–1430) and the net result 4100 that of
        Form 2, so that the forms agree; 4290 «Інші зміни в капіталі» takes
        the difference the rounding leaves, and the totals are added up."""
        self.ensure_one()
        start = self._form1_column(fields.Date.subtract(self.date_from, days=1))
        end = self._form1_column(self.date_to)
        values = {}
        for line in self.line_ids.filtered('code'):
            values[line.code] = {f: to_thousands(line[f]) for f in EQUITY_FIELDS}
        if '4110' in values:
            parts = [c for c in values if c in ('4111', '4112', '4113', '4114', '4116')]
            if parts:
                values['4110'] = {f: round_units(sum(values[c][f] for c in parts)) for f in EQUITY_FIELDS}
        if '4100' in values:
            values['4100']['retained'] = self._net_profit_thousands()
        for f in EQUITY_FIELDS:
            values['4000'][f] = start.get(EQUITY_FORM1_ROWS[f], 0.0)
            values['4300'][f] = end.get(EQUITY_FORM1_ROWS[f], 0.0)
            values['4095'][f] = round_units(
                values['4000'][f] + sum(values[c][f] for c in EQUITY_MANUAL_CODES if c in values))
            values['4295'][f] = round_units(values['4300'][f] - values['4095'][f])
            others = sum(values[c][f] for c in EQUITY_CHANGE_CODES if c in values and c != '4290')
            values['4290'][f] = round_units(values['4295'][f] - others)
        for code, row in values.items():
            row['total'] = round_units(sum(row[f] for f in EQUITY_FIELDS))
        return values

    @api.model
    def _ua_fmt(self, amount):
        return format_units(amount, parentheses=True)

    def _xml_values(self):
        """{'R4000G3': 1234, …}: thousands without decimals (DGdecimal0 of
        J0901005). Negative amounts keep their sign (TODO(#78): confirm
        against an accepted J0901005). Empty cells are left out."""
        self.ensure_one()
        graphs = dict((col[0], col[1]) for col in EQUITY_COLUMNS)
        values = {}
        for code, row in self._form_values().items():
            for field, amount in row.items():
                if amount:
                    graph = 10 if field == 'total' else graphs[field]
                    values[f'R{code}G{graph}'] = int(amount)
        return values

    # ── XLSX ────────────────────────────────────────────────

    def _write_equity_xlsx(self, workbook):
        sheet = workbook.add_worksheet('Ф4')
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        subtitle_fmt = workbook.add_format({'bold': True, 'align': 'center'})
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white', 'border': 1,
            'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
        })
        text_fmt = workbook.add_format({'border': 1, 'text_wrap': True})
        sub_fmt = workbook.add_format({'border': 1, 'italic': True, 'indent': 2, 'text_wrap': True})
        bold_fmt = workbook.add_format({'border': 1, 'bold': True, 'text_wrap': True})
        code_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        bold_money_fmt = workbook.add_format({'border': 1, 'bold': True, 'num_format': '#,##0.00'})

        sheet.set_column('A:A', 48)
        sheet.set_column('B:B', 8)
        sheet.set_column('C:J', 15)
        sheet.merge_range(0, 0, 0, 9, 'Звіт про власний капітал', title_fmt)
        sheet.merge_range(1, 0, 1, 9, self.name, subtitle_fmt)
        sheet.merge_range(2, 0, 2, 9, self.company_id.name, subtitle_fmt)
        headers = ['Стаття', 'Код рядка', 'Зареєстрований (пайовий) капітал',
                   'Капітал у дооцінках', 'Додатковий капітал', 'Резервний капітал',
                   'Нерозподілений прибуток (непокритий збиток)', 'Неоплачений капітал',
                   'Вилучений капітал', 'Всього']
        row = 4
        sheet.set_row(row, 45)
        for col, header in enumerate(headers):
            sheet.write(row, col, header, header_fmt)
        row += 1
        for line in self.line_ids.sorted('sequence'):
            bold = line.line_type in ('opening', 'subtotal', 'total', 'closing')
            if line.line_type == 'header':
                sheet.write(row, 0, line.name, text_fmt)
                for col in range(1, 10):
                    sheet.write(row, col, '', text_fmt)
            else:
                name_fmt = sub_fmt if line.line_type == 'sub' else (bold_fmt if bold else text_fmt)
                sheet.write(row, 0, line.name, name_fmt)
                sheet.write(row, 1, line.code, code_fmt)
                for col, field in enumerate(EQUITY_FIELDS + ['total'], start=2):
                    sheet.write(row, col, line[field], bold_money_fmt if bold else money_fmt)
            row += 1


class L10nUaEquityReportLine(models.Model):
    _name = 'l10n_ua.equity.report.line'
    _description = 'Statement of Changes in Equity Line'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.equity.report', string='Report', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Line Name')
    code = fields.Char(string='Row Code')
    parent_code = fields.Char(string='Part of Row')
    line_type = fields.Selection(
        [('header', 'Group Title'),
         ('opening', 'Opening Balance'),
         ('manual', 'Adjustment (entered by hand)'),
         ('detail', 'Detail'),
         ('sub', 'Including (not in totals)'),
         ('subtotal', 'Adjusted Opening Balance'),
         ('total', 'Total Changes'),
         ('closing', 'Closing Balance')],
        string='Line Type', default='detail',
    )
    currency_id = fields.Many2one('res.currency', related='report_id.currency_id')
    registered = fields.Monetary(string='Registered Capital', currency_field='currency_id')
    revaluation = fields.Monetary(string='Revaluation Reserve', currency_field='currency_id')
    additional = fields.Monetary(string='Additional Capital', currency_field='currency_id')
    reserve = fields.Monetary(string='Reserve Capital', currency_field='currency_id')
    retained = fields.Monetary(string='Retained Earnings', currency_field='currency_id')
    unpaid = fields.Monetary(string='Unpaid Capital', currency_field='currency_id')
    withdrawn = fields.Monetary(string='Withdrawn Capital', currency_field='currency_id')
    total = fields.Monetary(
        string='Total', compute='_compute_total', store=True, currency_field='currency_id')

    @api.depends(*EQUITY_FIELDS)
    def _compute_total(self):
        for line in self:
            line.total = sum(line[f] for f in EQUITY_FIELDS)

    def write(self, vals):
        if any(f in vals for f in EQUITY_FIELDS) and not self.env.context.get(
                'l10n_ua_equity_no_recompute'):
            if self.filtered(lambda l: l.report_id.state != 'draft'):
                raise UserError(_('A confirmed report cannot be changed. Set it back to draft first.'))
            if self.filtered(lambda l: l.line_type != 'manual'):
                raise UserError(_(
                    'Only the rows «Коригування» (4005, 4010, 4090) are entered by hand; '
                    'the other rows come from the ledger. Recalculate the report instead.'))
            old = {line: {f: line[f] for f in EQUITY_FIELDS} for line in self}
            res = super().write(vals)
            # The correction was posted in the period and went to 4290
            for line in self:
                other = line.report_id.line_ids.filtered(lambda l: l.code == '4290')
                other.with_context(l10n_ua_equity_no_recompute=True).write({
                    f: other[f] - (line[f] - old[line][f]) for f in EQUITY_FIELDS})
            self.report_id._recompute_totals()
            return res
        return super().write(vals)
