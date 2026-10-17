"""Ukrainian Balance Sheet (Баланс, Форма №1) — persistent stored report."""

import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# Line definitions: (sequence, key, name, code, section, line_type, account_codes, balance_type)
#
# Rows, their order and codes are those of Додаток 1 до НП(С)БО 1 (наказ
# Мінфіну № 73 від 07.02.2013, z0336-13, ред. від 23.12.2025). The rows 1120,
# 1605 and 1635 are additional articles of Додаток 3 (п. 4 розд. II НП(С)БО 1):
# they are included in the total (пп. 2.26, 2.60, 2.66 Методичних рекомендацій
# щодо заповнення форм фінансової звітності, наказ Мінфіну № 433 від
# 28.03.2013), so they are detail rows, but they are printed only when they
# hold an amount (``BALANCE_ADDITIONAL_CODES``). The rows «у тому числі» and
# the components of a row (1001/1002, 1011/1012, 1136, 1621) are in
# ``BALANCE_SUB_LINES``: they are not part of any total.
#
# Accounts are those of the Інструкція про застосування Плану рахунків (наказ
# Мінфіну № 291 від 30.11.1999): 41 «Капітал у дооцінках» → 1405 (п. 2.41 МР),
# 54 «Відстрочені податкові зобов'язання» → 1500 (п. 2.48), 141 «Інвестиції
# пов'язаним сторонам за методом обліку участі в капіталі» → 1030, other 14 →
# 1035 (п. 2.12), 184 «Інші необоротні активи» → 1090 (п. 2.18), 21 «Поточні
# біологічні активи» → 1110 (п. 2.24), 286 «Необоротні активи та групи
# вибуття, утримувані для продажу» → 1200 (п. 2.39), 505/506 «Інші
# довгострокові позики» → 1515, not 1510 (пп. 2.50, 2.51), 680 «Розрахунки,
# пов'язані з необоротними активами та групами вибуття, утримуваними для
# продажу» → 1700 (п. 2.74).
# 1520 «Довгострокові забезпечення» has no account: the chart keeps all
# provisions on 47 without a split by term (пп. 2.52, 2.70 МР), so 47 stays in
# 1660 «Поточні забезпечення».
#
# Every account goes to exactly one detail row: the row with the longest
# matching prefix (e.g. 100 → 1015, not 1010). A prefix listed in both an asset
# and a liability row (36, 37, 63, 641, 642, 643, 644, 68) is a settlement
# account with a «розгорнуте сальдо»: its balance per account and partner goes to the asset
# row when it is a debit and to the liability row when it is a credit.
# Asset rows show debit − credit, equity and liability rows credit − debit, so
# contra accounts (13x, 38, 45, 46) come out negative within their row.
# ПДВ on 643 «Податкові зобов'язання» and 644 «Податковий кредит» is not a
# settlement with the budget (1135/1620): a debit balance goes to 1190 «Інші
# оборотні активи», a credit one to 1690 «Інші поточні зобов'язання» (643
# usually has a debit balance after an advance received, 644 a credit one
# after an advance paid, a debit one for an unregistered tax invoice).
# Classes 7–9 not yet closed go to 1420: a balance built before the period is
# closed must still balance.
BALANCE_LINES = [
    # I. Необоротні активи
    (100, 'section_noncurrent', 'I. Необоротні активи', '', 'asset_noncurrent', 'section', '', ''),
    (110, 'intangible_assets', 'Нематеріальні активи', '1000', 'asset_noncurrent', 'detail', '12,133', 'balance'),
    (120, 'unfinished_capex', 'Незавершені капітальні інвестиції', '1005', 'asset_noncurrent', 'detail', '15', 'balance'),
    (130, 'fixed_assets', 'Основні засоби', '1010', 'asset_noncurrent', 'detail', '10,11,131,132', 'balance'),
    (140, 'investment_property', 'Інвестиційна нерухомість', '1015', 'asset_noncurrent', 'detail', '100,135', 'balance'),
    (142, 'lt_biological_assets', 'Довгострокові біологічні активи', '1020', 'asset_noncurrent', 'detail', '16,134', 'balance'),
    (145, 'lt_financial_investments', 'Довгострокові фінансові інвестиції, які обліковуються за методом участі в капіталі інших підприємств', '1030', 'asset_noncurrent', 'detail', '141', 'balance'),
    (146, 'lt_other_investments', 'Інші довгострокові фінансові інвестиції', '1035', 'asset_noncurrent', 'detail', '14', 'balance'),
    (150, 'long_term_receivables', 'Довгострокова дебіторська заборгованість', '1040', 'asset_noncurrent', 'detail', '18', 'balance'),
    (160, 'deferred_tax_assets', 'Відстрочені податкові активи', '1045', 'asset_noncurrent', 'detail', '17', 'balance'),
    (170, 'other_noncurrent_assets', 'Інші необоротні активи', '1090', 'asset_noncurrent', 'detail', '184', 'balance'),
    (190, 'subtotal_noncurrent', 'Усього за розділом I', '1095', 'asset_noncurrent', 'subtotal', '', ''),

    # II. Оборотні активи
    (200, 'section_current', 'II. Оборотні активи', '', 'asset_current', 'section', '', ''),
    (210, 'inventories', 'Запаси', '1100', 'asset_current', 'detail', '20,22,23,24,25,26,27,28', 'balance'),
    (212, 'current_biological_assets', 'Поточні біологічні активи', '1110', 'asset_current', 'detail', '21', 'balance'),
    (215, 'bills_received', 'Векселі одержані', '1120', 'asset_current', 'detail', '34', 'balance'),
    (220, 'receivables_goods', 'Дебіторська заборгованість за продукцію, товари, роботи, послуги', '1125', 'asset_current', 'detail', '36,38', 'balance'),
    (225, 'receivables_advances', 'Дебіторська заборгованість за розрахунками за виданими авансами', '1130', 'asset_current', 'detail', '63,371', 'balance'),
    (230, 'receivables_budget', 'Дебіторська заборгованість за розрахунками з бюджетом', '1135', 'asset_current', 'detail', '641,642', 'balance'),
    (240, 'other_current_receivables', 'Інша поточна дебіторська заборгованість', '1155', 'asset_current', 'detail', '37,68', 'balance'),
    (245, 'current_investments', 'Поточні фінансові інвестиції', '1160', 'asset_current', 'detail', '35', 'balance'),
    (250, 'cash', 'Гроші та їх еквіваленти', '1165', 'asset_current', 'detail', '30,31,33', 'balance'),
    (260, 'prepaid_expenses', 'Витрати майбутніх періодів', '1170', 'asset_current', 'detail', '39', 'balance'),
    (270, 'other_current_assets', 'Інші оборотні активи', '1190', 'asset_current', 'detail', '643,644', 'balance'),
    (290, 'subtotal_current', 'Усього за розділом II', '1195', 'asset_current', 'subtotal', '', ''),

    # III. Необоротні активи, утримувані для продажу, та групи вибуття:
    # a section that is a single row
    (295, 'held_for_sale_assets', 'III. Необоротні активи, утримувані для продажу, та групи вибуття', '1200', 'asset_held_for_sale', 'detail', '286', 'balance'),

    (300, 'total_assets', 'БАЛАНС', '1300', '', 'total', '', ''),

    # I. Власний капітал
    (400, 'section_equity', 'I. Власний капітал', '', 'equity', 'section', '', ''),
    (410, 'registered_capital', 'Зареєстрований (пайовий) капітал', '1400', 'equity', 'detail', '40', 'balance'),
    (415, 'revaluation_capital', 'Капітал у дооцінках', '1405', 'equity', 'detail', '41', 'balance'),
    (420, 'additional_capital', 'Додатковий капітал', '1410', 'equity', 'detail', '42', 'balance'),
    (430, 'reserve_capital', 'Резервний капітал', '1415', 'equity', 'detail', '43', 'balance'),
    (440, 'retained_earnings', 'Нерозподілений прибуток (непокритий збиток)', '1420', 'equity', 'detail', '44,7,8,9', 'balance'),
    (445, 'unpaid_capital', 'Неоплачений капітал', '1425', 'equity', 'detail', '46', 'balance'),
    (446, 'withdrawn_capital', 'Вилучений капітал', '1430', 'equity', 'detail', '45', 'balance'),
    (490, 'subtotal_equity', 'Усього за розділом I', '1495', 'equity', 'subtotal', '', ''),

    # II. Довгострокові зобов'язання і забезпечення
    (500, 'section_lt_liab', "II. Довгострокові зобов'язання і забезпечення", '', 'liability_longterm', 'section', '', ''),
    (505, 'deferred_tax_liabilities', "Відстрочені податкові зобов'язання", '1500', 'liability_longterm', 'detail', '54', 'balance'),
    (510, 'long_term_loans', 'Довгострокові кредити банків', '1510', 'liability_longterm', 'detail', '50', 'balance'),
    (520, 'long_term_liabilities', "Інші довгострокові зобов'язання", '1515', 'liability_longterm', 'detail', '505,506,51,52,53,55', 'balance'),
    (522, 'lt_provisions', 'Довгострокові забезпечення', '1520', 'liability_longterm', 'detail', '', 'balance'),
    (525, 'target_financing', 'Цільове фінансування', '1525', 'liability_longterm', 'detail', '48', 'balance'),
    (590, 'subtotal_lt_liab', 'Усього за розділом II', '1595', 'liability_longterm', 'subtotal', '', ''),

    # III. Поточні зобов'язання і забезпечення
    (600, 'section_ct_liab', "III. Поточні зобов'язання і забезпечення", '', 'liability_current', 'section', '', ''),
    (610, 'short_term_loans', 'Короткострокові кредити банків', '1600', 'liability_current', 'detail', '60', 'balance'),
    (612, 'bills_issued', 'Векселі видані', '1605', 'liability_current', 'detail', '62', 'balance'),
    (614, 'current_lt_debt', "Поточна кредиторська заборгованість за довгостроковими зобов'язаннями", '1610', 'liability_current', 'detail', '61', 'balance'),
    (620, 'payables_goods', 'Поточна кредиторська заборгованість за товари, роботи, послуги', '1615', 'liability_current', 'detail', '63', 'balance'),
    (630, 'payables_budget', 'Поточна кредиторська заборгованість за розрахунками з бюджетом', '1620', 'liability_current', 'detail', '641,642', 'balance'),
    (640, 'payables_insurance', 'Поточна кредиторська заборгованість за розрахунками зі страхування', '1625', 'liability_current', 'detail', '65', 'balance'),
    (650, 'payables_wages', 'Поточна кредиторська заборгованість за розрахунками з оплати праці', '1630', 'liability_current', 'detail', '66', 'balance'),
    (655, 'payables_advances', 'Поточна кредиторська заборгованість за одержаними авансами', '1635', 'liability_current', 'detail', '36,681', 'balance'),
    (660, 'current_provisions', 'Поточні забезпечення', '1660', 'liability_current', 'detail', '47', 'balance'),
    (665, 'deferred_income', 'Доходи майбутніх періодів', '1665', 'liability_current', 'detail', '69', 'balance'),
    (670, 'other_current_liabilities', "Інші поточні зобов'язання", '1690', 'liability_current', 'detail', '37,643,644,67,68', 'balance'),
    (690, 'subtotal_ct_liab', 'Усього за розділом III', '1695', 'liability_current', 'subtotal', '', ''),

    # IV. Зобов'язання, пов'язані з необоротними активами, утримуваними для
    # продажу, та групами вибуття: a section that is a single row
    (695, 'held_for_sale_liabilities', "IV. Зобов'язання, пов'язані з необоротними активами, утримуваними для продажу, та групами вибуття", '1700', 'liability_held_for_sale', 'detail', '680', 'balance'),

    (700, 'total_liabilities', 'БАЛАНС', '1900', '', 'total', '', ''),
]

# Rows «у тому числі» and the components of a detail row:
# (sequence, key, name, code, parent row key, account_codes).
# An account counts in such a row only when the parent row takes it, so a
# credit balance of 6413 is in 1621 and never in 1136. The amount has the sign
# of the parent row, so 1001 + 1002 = 1000 (накопичена амортизація and знос
# come out negative, as the contra accounts of the other rows). They are not
# added to any total.
# 1136/1621 «з податку на прибуток»: the Instruction № 291 has no subaccount
# for it (only analytics of 641); 6413 is the subaccount «Розрахунки за
# податком на прибуток» of the chart of accounts of Odoo (l10n_ua, ua_psbo).
BALANCE_SUB_LINES = [
    (111, 'intangible_assets_cost', 'первісна вартість', '1001', 'intangible_assets', '12'),
    (112, 'intangible_assets_amortization', 'накопичена амортизація', '1002', 'intangible_assets', '133'),
    (131, 'fixed_assets_cost', 'первісна вартість', '1011', 'fixed_assets', '10,11'),
    (132, 'fixed_assets_depreciation', 'знос', '1012', 'fixed_assets', '131,132'),
    (231, 'receivables_budget_profit_tax', 'у тому числі з податку на прибуток', '1136', 'receivables_budget', '6413'),
    (631, 'payables_budget_profit_tax', 'у тому числі з податку на прибуток', '1621', 'payables_budget', '6413'),
]

# Additional articles (Додаток 3 до НП(С)БО 1), printed only with an amount.
BALANCE_ADDITIONAL_CODES = ('1120', '1605', '1635')

ASSET_SECTIONS = ('asset_noncurrent', 'asset_current', 'asset_held_for_sale')
LIABILITY_SECTIONS = ('equity', 'liability_longterm', 'liability_current', 'liability_held_for_sale')
BALANCE_DETAIL_LINES = [line for line in BALANCE_LINES if line[5] == 'detail']
BALANCE_SECTION_OF = {line[1]: line[4] for line in BALANCE_DETAIL_LINES}


def balance_row_prefixes(line):
    return [c.strip() for c in (line[6] or '').split(',') if c.strip()]


def match_balance_sub_lines(code, row_key):
    """Keys of the rows «у тому числі» of detail row ``row_key`` that take
    the account ``code``."""
    return [
        sub[1] for sub in BALANCE_SUB_LINES
        if sub[4] == row_key and any(
            code.startswith(p.strip()) for p in sub[5].split(',') if p.strip())
    ]


def match_balance_line(code, amount):
    """The key of the Form 1 detail row an account goes to, or None.

    The longest matching prefix wins; a prefix shared by an asset and a
    liability row goes to the asset row for a debit balance (``amount`` ≥ 0)
    and to the liability row for a credit one.
    """
    best_len, candidates = 0, []
    for line in BALANCE_DETAIL_LINES:
        for prefix in balance_row_prefixes(line):
            if not code.startswith(prefix):
                continue
            if len(prefix) > best_len:
                best_len, candidates = len(prefix), [line]
            elif len(prefix) == best_len and line not in candidates:
                candidates.append(line)
    if not candidates:
        return None
    if len(candidates) > 1:
        wanted = ASSET_SECTIONS if amount >= 0 else LIABILITY_SECTIONS
        for line in candidates:
            if line[4] in wanted:
                return line[1]
    return candidates[0][1]


class L10nUaBalanceReport(models.Model):
    _name = 'l10n_ua.balance.report'
    _description = 'Balance Sheet (Form №1)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    date_to = fields.Date(
        string='Report Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    comparison_date = fields.Date(
        string='Comparison Date',
        help='Date for comparison column (typically end of previous year)',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
        ],
        string='State',
        default='draft',
        tracking=True,
    )
    line_ids = fields.One2many(
        'l10n_ua.balance.report.line',
        'report_id',
        string='Lines',
    )
    total_assets = fields.Monetary(
        string='Total Assets',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_liabilities = fields.Monetary(
        string='Total Liabilities & Equity',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    note = fields.Text(string='Notes')
    unmapped_accounts = fields.Char(
        string='Accounts Without a Row',
        readonly=True,
        help='Accounts with a balance that no row of the form takes. Their '
             'balance is left out, so the two sides of the balance differ by it.',
    )

    @api.depends('date_to', 'company_id')
    def _compute_name(self):
        for rec in self:
            date_str = rec.date_to.strftime('%d.%m.%Y') if rec.date_to else ''
            rec.name = f"Баланс на {date_str}"

    @api.depends('line_ids.current_amount', 'line_ids.line_type')
    def _compute_totals(self):
        for rec in self:
            total_a = 0.0
            total_l = 0.0
            for line in rec.line_ids:
                if line.line_type == 'total' and line.code == '1300':
                    total_a = line.current_amount
                elif line.line_type == 'total' and line.code == '1900':
                    total_l = line.current_amount
            rec.total_assets = total_a
            rec.total_liabilities = total_l

    # ── Actions ─────────────────────────────────────────────

    def action_compute(self):
        """(Re)calculate all lines from account.move.line."""
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
        return self.env.ref(
            'l10n_ua_accounting.action_report_balance_sheet'
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Run: pip install xlsxwriter'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_balance_xlsx(workbook)
        workbook.close()
        output.seek(0)

        filename = f"Баланс_{self.date_to.strftime('%d.%m.%Y')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ── Data generation ─────────────────────────────────────

    def _get_row_groups(self, date):
        """Balances per account and partner at a date, with the detail row
        (``match_balance_line``) each of them goes to.

        :return: list of (account, partner, balance, row key or None)
        """
        self.ensure_one()
        MoveLine = self.env['account.move.line'].with_company(self.company_id)
        groups = MoveLine._read_group(
            [('date', '<=', date),
             ('parent_state', '=', 'posted'),
             ('company_id', '=', self.company_id.id)],
            ['account_id', 'partner_id'],
            ['balance:sum'],
        )
        return [
            (account, partner, balance,
             match_balance_line(account.with_company(self.company_id).code or '', balance))
            for account, partner, balance in groups
        ]

    def _get_row_amounts(self, date):
        """Signed amounts of the detail rows at a date, and the unmapped accounts.

        Balances are taken per account and partner, so that a settlement
        account shows both its debit and its credit side (розгорнуте сальдо).
        Account codes are those of the report's company.

        The rows «у тому числі» (``BALANCE_SUB_LINES``) get the part of
        their parent row that their accounts make up.

        :return: ({row key: amount}, {account code: balance})
        """
        self.ensure_one()
        amounts, unmapped = {}, {}
        currency = self.company_id.currency_id
        for account, _partner, balance, key in self._get_row_groups(date):
            if currency.is_zero(balance):
                continue
            code = account.with_company(self.company_id).code or ''
            if not key:
                unmapped[code] = unmapped.get(code, 0.0) + balance
                continue
            value = balance if BALANCE_SECTION_OF[key] in ASSET_SECTIONS else -balance
            for row_key in [key] + match_balance_sub_lines(code, key):
                amounts[row_key] = amounts.get(row_key, 0.0) + value
        return amounts, unmapped

    def _generate_lines(self):
        """Generate report lines from account.move.line data."""
        self.ensure_one()
        date_end = self.date_to
        date_comp = self.comparison_date or fields.Date.from_string(
            f'{self.date_to.year - 1}-12-31'
        )

        current, unmapped = self._get_row_amounts(date_end)
        previous, _unmapped_prev = self._get_row_amounts(date_comp)
        amounts = {}
        sections = {}
        for line in BALANCE_DETAIL_LINES:
            key, section = line[1], line[4]
            cur, prev = current.get(key, 0.0), previous.get(key, 0.0)
            amounts[key] = (cur, prev)
            sec_cur, sec_prev = sections.get(section, (0.0, 0.0))
            sections[section] = (sec_cur + cur, sec_prev + prev)
        for seq, key, name, code, section, line_type, acct_codes, bal_type in BALANCE_LINES:
            if line_type == 'subtotal':
                amounts[key] = sections.get(section, (0.0, 0.0))
        for key, side in (('total_assets', ASSET_SECTIONS),
                          ('total_liabilities', LIABILITY_SECTIONS)):
            amounts[key] = (
                sum(sections.get(s, (0.0, 0.0))[0] for s in side),
                sum(sections.get(s, (0.0, 0.0))[1] for s in side),
            )
        self.unmapped_accounts = ', '.join(
            '%s: %s' % (code, self.company_id.currency_id.format(balance))
            for code, balance in sorted(unmapped.items())) or False

        for sub in BALANCE_SUB_LINES:
            key = sub[1]
            amounts[key] = (current.get(key, 0.0), previous.get(key, 0.0))

        # Create line records
        currency = self.company_id.currency_id
        rows = list(BALANCE_LINES) + [
            (seq, key, name, code, BALANCE_SECTION_OF[parent], 'sub', acct_codes, 'balance')
            for seq, key, name, code, parent, acct_codes in BALANCE_SUB_LINES
        ]
        vals_list = []
        for seq, key, name, code, section, line_type, acct_codes, bal_type in sorted(rows):
            cur, prev = amounts.get(key, (0.0, 0.0))
            if (code in BALANCE_ADDITIONAL_CODES
                    and currency.is_zero(cur) and currency.is_zero(prev)):
                continue
            vals_list.append({
                'report_id': self.id,
                'sequence': seq,
                'name': name,
                'code': code,
                'section': section or False,
                'line_type': line_type,
                'account_codes': acct_codes,
                'balance_type': bal_type,
                'current_amount': cur,
                'previous_amount': prev,
            })
        self.env['l10n_ua.balance.report.line'].create(vals_list)

    # ── XLSX ────────────────────────────────────────────────

    def _write_balance_xlsx(self, workbook):
        """Write Balance Sheet data to an xlsxwriter workbook."""
        worksheet = workbook.add_worksheet('Баланс')

        title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        subtitle_fmt = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'center'})
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
        })
        section_fmt = workbook.add_format({'bold': True, 'bg_color': '#D9E2F3', 'border': 1})
        line_fmt = workbook.add_format({'border': 1})
        sub_fmt = workbook.add_format({'border': 1, 'italic': True, 'indent': 2})
        code_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        subtotal_fmt = workbook.add_format({'bold': True, 'border': 1, 'top': 2})
        subtotal_money_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'border': 1, 'top': 2})
        total_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'border': 2})
        total_money_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'num_format': '#,##0.00', 'border': 2})

        worksheet.set_column('A:A', 55)
        worksheet.set_column('B:B', 12)
        worksheet.set_column('C:C', 18)
        worksheet.set_column('D:D', 18)

        date_comp = self.comparison_date or fields.Date.from_string(f'{self.date_to.year - 1}-12-31')

        row = 0
        worksheet.merge_range(row, 0, row, 3, 'Баланс (Звіт про фінансовий стан)', title_fmt)
        row += 1
        worksheet.merge_range(row, 0, row, 3, f"на {self.date_to.strftime('%d.%m.%Y')}", subtitle_fmt)
        row += 1
        worksheet.merge_range(row, 0, row, 3, self.company_id.name, subtitle_fmt)
        row += 2

        worksheet.write(row, 0, 'Стаття', header_fmt)
        worksheet.write(row, 1, 'Код рядка', header_fmt)
        worksheet.write(row, 2, f"На {self.date_to.strftime('%d.%m.%Y')}", header_fmt)
        worksheet.write(row, 3, f"На {date_comp.strftime('%d.%m.%Y')}", header_fmt)
        row += 1

        for line in self.line_ids.sorted('sequence'):
            if line.line_type == 'section':
                worksheet.merge_range(row, 0, row, 3, line.name, section_fmt)
            elif line.line_type == 'subtotal':
                worksheet.write(row, 0, line.name, subtotal_fmt)
                worksheet.write(row, 1, line.code, subtotal_fmt)
                worksheet.write(row, 2, line.current_amount, subtotal_money_fmt)
                worksheet.write(row, 3, line.previous_amount, subtotal_money_fmt)
            elif line.line_type == 'total':
                worksheet.write(row, 0, line.name, total_fmt)
                worksheet.write(row, 1, line.code, total_fmt)
                worksheet.write(row, 2, line.current_amount, total_money_fmt)
                worksheet.write(row, 3, line.previous_amount, total_money_fmt)
            else:
                worksheet.write(row, 0, line.name, sub_fmt if line.line_type == 'sub' else line_fmt)
                worksheet.write(row, 1, line.code, code_fmt)
                worksheet.write(row, 2, line.current_amount, money_fmt)
                worksheet.write(row, 3, line.previous_amount, money_fmt)
            row += 1


class L10nUaBalanceReportLine(models.Model):
    _name = 'l10n_ua.balance.report.line'
    _description = 'Balance Sheet Line'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.balance.report',
        string='Report',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Line Name')
    code = fields.Char(string='Row Code')
    section = fields.Selection(
        selection=[
            ('asset_noncurrent', 'Non-current Assets'),
            ('asset_current', 'Current Assets'),
            ('equity', 'Equity'),
            ('liability_longterm', 'Long-term Liabilities'),
            ('liability_current', 'Current Liabilities'),
            ('asset_held_for_sale', 'Non-current Assets Held for Sale'),
            ('liability_held_for_sale', 'Liabilities of Disposal Groups Held for Sale'),
        ],
        string='Section',
    )
    line_type = fields.Selection(
        selection=[
            ('section', 'Section Header'),
            ('detail', 'Detail'),
            ('sub', 'Including (not in totals)'),
            ('subtotal', 'Subtotal'),
            ('total', 'Total'),
        ],
        string='Line Type',
        default='detail',
    )
    account_codes = fields.Char(
        string='Account Codes',
        help='Comma-separated account code prefixes used to compute this line',
    )
    balance_type = fields.Char(string='Balance Type')
    currency_id = fields.Many2one(
        'res.currency',
        related='report_id.currency_id',
    )
    current_amount = fields.Monetary(
        string='Current Period',
        currency_field='currency_id',
    )
    previous_amount = fields.Monetary(
        string='Previous Period',
        currency_field='currency_id',
    )

    def action_view_move_lines(self):
        """Drill-down: open journal items that compose this line.

        The accounts are resolved as for the amount (``match_balance_line``):
        an account of a longer prefix of another row is left out, and of a
        settlement account with a «розгорнуте сальдо» only the partners whose
        balance is on this row's side are shown. A row «у тому числі» shows
        the part of its parent row it is made of.
        """
        self.ensure_one()
        if not self.account_codes or self.line_type in ('section', 'subtotal', 'total'):
            return
        report = self.report_id
        row_key = next((line[1] for line in BALANCE_DETAIL_LINES + BALANCE_SUB_LINES
                        if line[3] == self.code), None)

        def takes(code, key):
            return bool(key) and (key == row_key or row_key in match_balance_sub_lines(code, key))

        currency = report.company_id.currency_id
        accounts, partners_by_account = set(), {}
        for account, partner, balance, key in report._get_row_groups(report.date_to):
            code = account.with_company(report.company_id).code or ''
            split = (takes(code, match_balance_line(code, 1.0))
                     != takes(code, match_balance_line(code, -1.0)))
            if not split:
                if takes(code, key):
                    accounts.add(account.id)
            elif takes(code, key) and not currency.is_zero(balance):
                partners_by_account.setdefault(account.id, []).append(partner.id or False)
        account_domain = []
        if accounts:
            account_domain.append([('account_id', 'in', sorted(accounts))])
        for account_id, partner_ids in partners_by_account.items():
            partner_domain = [('partner_id', 'in', [p for p in partner_ids if p])]
            if False in partner_ids:
                partner_domain = ['|', ('partner_id', '=', False)] + partner_domain
            account_domain.append(['&', ('account_id', '=', account_id)] + partner_domain)
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', report.company_id.id),
            ('date', '<=', report.date_to),
        ]
        if account_domain:
            domain += ['|'] * (len(account_domain) - 1) + [
                leaf for part in account_domain for leaf in part]
        else:
            domain.append(('id', '=', 0))
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} ({self.code})',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
        }
