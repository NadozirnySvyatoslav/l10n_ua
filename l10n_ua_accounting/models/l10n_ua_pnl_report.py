"""Ukrainian P&L Statement (Звіт про фінансові результати, Форма №2) — persistent stored report.

Rows are those of Додаток 1 до НП(С)БО 1 (наказ Мінфіну № 73 від 07.02.2013,
z0336-13, ред. від 23.12.2025): I. Фінансові результати, II. Сукупний дохід,
III. Елементи операційних витрат, IV. Розрахунок показників прибутковості
акцій. The XML elements of J0900207 carry the same codes: R2000G3 (звітний
період), R2000G4 (попередній).

A row of section I is the net turnover of its accounts in the period (credit −
debit for an income row, debit − credit for an expense row), leaving out the
entries that close the period through 79 «Фінансові результати»: a return of
goods (Дт 70) lowers the net revenue, a reversal of an expense lowers the
expense, and the closing itself does not wipe the year out (п. 3.3, 3.5
Методичних рекомендацій № 433, П(С)БО 15). ``pnl_amount`` and
``pnl_closing_move_domain`` are the rule; l10n_ua_consolidation uses them too,
so that form 2-к adds up the forms 2 of the group.

A result row of the paper form is a pair: profit and loss (2090/2095,
2190/2195, 2290/2295, 2350/2355); the loss row shows the amount without sign
and is printed in parentheses. The subtotal line keeps the signed amount,
its loss twin (``PNL_LOSS_CODES``) is added next to it.
"""

import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# Section I. Line definitions:
# (sequence, key, name, code, line_type, account_codes, turnover_type)
# turnover_type: 'credit' — an income row (added to the result), 'debit' — an
# expense row (subtracted); '' for a computed row. l10n_ua_consolidation reads
# this list (form 2-к): keep its shape.
PNL_LINES = [
    (10, 'net_revenue', 'Чистий дохід від реалізації продукції (товарів, робіт, послуг)', '2000', 'detail', '70', 'credit'),
    (20, 'cost_of_sales', 'Собівартість реалізованої продукції (товарів, робіт, послуг)', '2050', 'detail', '90', 'debit'),
    (30, 'gross_profit', 'Валовий: прибуток', '2090', 'subtotal', '', ''),
    (40, 'other_operating_income', 'Інші операційні доходи', '2120', 'detail', '71', 'credit'),
    (50, 'administrative_expenses', 'Адміністративні витрати', '2130', 'detail', '92', 'debit'),
    (60, 'selling_expenses', 'Витрати на збут', '2150', 'detail', '93', 'debit'),
    (70, 'other_operating_expenses', 'Інші операційні витрати', '2180', 'detail', '94', 'debit'),
    (80, 'operating_profit', 'Фінансовий результат від операційної діяльності: прибуток', '2190', 'subtotal', '', ''),
    (85, 'equity_income', 'Дохід від участі в капіталі', '2200', 'detail', '72', 'credit'),
    (90, 'financial_income', 'Інші фінансові доходи', '2220', 'detail', '73', 'credit'),
    (95, 'other_income', 'Інші доходи', '2240', 'detail', '74', 'credit'),
    (100, 'financial_expenses', 'Фінансові витрати', '2250', 'detail', '95', 'debit'),
    (105, 'equity_losses', 'Втрати від участі в капіталі', '2255', 'detail', '96', 'debit'),
    (110, 'other_expenses', 'Інші витрати', '2270', 'detail', '97', 'debit'),
    (130, 'profit_before_tax', 'Фінансовий результат до оподаткування: прибуток', '2290', 'subtotal', '', ''),
    (140, 'income_tax_expense', 'Витрати (дохід) з податку на прибуток', '2300', 'detail', '98', 'debit'),
    (145, 'discontinued_result', 'Прибуток (збиток) від припиненої діяльності після оподаткування', '2305', 'detail', '', 'credit'),
    (150, 'net_profit', 'Чистий фінансовий результат: прибуток', '2350', 'total', '', ''),
]

# Loss twins of the result rows: (code, name)
PNL_LOSS_CODES = {
    '2090': ('2095', 'Валовий: збиток'),
    '2190': ('2195', 'Фінансовий результат від операційної діяльності: збиток'),
    '2290': ('2295', 'Фінансовий результат до оподаткування: збиток'),
    '2350': ('2355', 'Чистий фінансовий результат: збиток'),
}

# Rows entered by hand: no account carries them. 2305 — припинена діяльність
# (П(С)БО 27), 2455 — податок на прибуток з іншого сукупного доходу,
# section IV — only for joint-stock companies.
PNL_MANUAL_CODES = ('2305', '2455', '2600', '2605', '2610', '2615', '2650')

# Sections II–IV: (sequence, key, name, code, line_type, account_codes)
# II. Other comprehensive income: credit − debit of the subaccounts of 41
# (Інструкція № 291: 411 дооцінка ОЗ, 412 НМА, 413 фінансових інструментів,
# 414 інший капітал у дооцінках), without the transfer of a realised surplus
# to 44 — the same entries as rows 4111–4116 of Форма № 4.
# III. Elements of operating expenses: the debit turnover of class 8.
PNL_EXTRA_LINES = [
    (200, 'section_oci', 'II. СУКУПНИЙ ДОХІД', '', 'section', ''),
    (210, 'oci_noncurrent', 'Дооцінка (уцінка) необоротних активів', '2400', 'oci', '411,412'),
    (220, 'oci_financial', 'Дооцінка (уцінка) фінансових інструментів', '2405', 'oci', '413'),
    (230, 'oci_fx', 'Накопичені курсові різниці', '2410', 'oci', ''),
    (240, 'oci_associates', 'Частка іншого сукупного доходу асоційованих та спільних підприємств', '2415', 'oci', ''),
    (250, 'oci_other', 'Інший сукупний дохід', '2445', 'oci', '414'),
    (260, 'oci_before_tax', 'Інший сукупний дохід до оподаткування', '2450', 'subtotal', ''),
    (270, 'oci_tax', "Податок на прибуток, пов'язаний з іншим сукупним доходом", '2455', 'manual', ''),
    (280, 'oci_after_tax', 'Інший сукупний дохід після оподаткування', '2460', 'subtotal', ''),
    (290, 'comprehensive_income', 'Сукупний дохід (сума рядків 2350, 2355 та 2460)', '2465', 'total', ''),
    (300, 'section_elements', 'III. ЕЛЕМЕНТИ ОПЕРАЦІЙНИХ ВИТРАТ', '', 'section', ''),
    (310, 'el_materials', 'Матеріальні затрати', '2500', 'element', '80'),
    (320, 'el_wages', 'Витрати на оплату праці', '2505', 'element', '81'),
    (330, 'el_social', 'Відрахування на соціальні заходи', '2510', 'element', '82'),
    (340, 'el_depreciation', 'Амортизація', '2515', 'element', '83'),
    (350, 'el_other', 'Інші операційні витрати', '2520', 'element', '84,85'),
    (360, 'el_total', 'Разом', '2550', 'subtotal', ''),
    (400, 'section_shares', 'IV. РОЗРАХУНОК ПОКАЗНИКІВ ПРИБУТКОВОСТІ АКЦІЙ', '', 'section', ''),
    (410, 'shares_avg', 'Середньорічна кількість простих акцій', '2600', 'manual', ''),
    (420, 'shares_avg_adj', 'Скоригована середньорічна кількість простих акцій', '2605', 'manual', ''),
    (430, 'eps', 'Чистий прибуток (збиток) на одну просту акцію', '2610', 'manual', ''),
    (440, 'eps_adj', 'Скоригований чистий прибуток (збиток) на одну просту акцію', '2615', 'manual', ''),
    (450, 'dps', 'Дивіденди на одну просту акцію', '2650', 'manual', ''),
]

# Section I is printed under its own title, after the header of the form.
PNL_SECTION_I = (5, 'section_results', 'I. ФІНАНСОВІ РЕЗУЛЬТАТИ', '', 'section', '', '')

# Rows whose amount is a count or hryvnias with kopecks (DGdecimal2 in J0900207)
PNL_SHARE_COUNT_CODES = ('2600', '2605')
PNL_DECIMAL2_CODES = ('2610', '2615', '2650')


def pnl_prefixes(account_codes):
    return [c.strip() for c in (account_codes or '').split(',') if c.strip()]


def pnl_amount(turnover_type, debit, credit):
    """Amount of a section I row from the turnover of its accounts: credit −
    debit for an income row, debit − credit for an expense row."""
    return credit - debit if turnover_type == 'credit' else debit - credit


def pnl_closing_move_domain(env, company, date_from, date_to):
    """Domain leaving out the entries that close the result through 79.

    An entry of the period with a line on 79 transfers incomes and expenses
    to the result (or the result to 44): it is not a turnover of the row.
    """
    closing_moves = env['account.move.line'].with_company(company).search([
        ('company_id', '=', company.id),
        ('parent_state', '=', 'posted'),
        ('date', '>=', date_from),
        ('date', '<=', date_to),
        ('account_id.code', '=like', '79%'),
    ]).move_id
    return [('move_id', 'not in', closing_moves.ids)] if closing_moves else []


def pnl_complete(amounts):
    """Fill the computed rows of the form from {key: amount} of the detail
    and manual rows; the result rows are signed (a loss is negative)."""
    a = dict(amounts)
    get = lambda key: a.get(key, 0.0)  # noqa: E731
    running = 0.0
    for seq, key, name, code, line_type, acct, turnover in PNL_LINES:
        if line_type == 'detail':
            running += get(key) if turnover == 'credit' else -get(key)
        else:
            a[key] = running
    a['oci_before_tax'] = sum(get(k) for k in (
        'oci_noncurrent', 'oci_financial', 'oci_fx', 'oci_associates', 'oci_other'))
    a['oci_after_tax'] = a['oci_before_tax'] - get('oci_tax')
    a['comprehensive_income'] = a['net_profit'] + a['oci_after_tax']
    a['el_total'] = sum(get(k) for k in (
        'el_materials', 'el_wages', 'el_social', 'el_depreciation', 'el_other'))
    return a

class L10nUaPnlReport(models.Model):
    _name = 'l10n_ua.pnl.report'
    _description = 'P&L Statement (Form №2)'
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
    date_from = fields.Date(
        string='Date From',
        required=True,
        tracking=True,
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    comparison_date_from = fields.Date(
        string='Comparison Period Start',
    )
    comparison_date_to = fields.Date(
        string='Comparison Period End',
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
        'l10n_ua.pnl.report.line',
        'report_id',
        string='Lines',
    )
    net_profit = fields.Monetary(
        string='Net Profit',
        compute='_compute_net_profit',
        store=True,
        currency_field='currency_id',
    )
    note = fields.Text(string='Notes')

    @api.depends('date_from', 'date_to', 'company_id')
    def _compute_name(self):
        for rec in self:
            fr = rec.date_from.strftime('%d.%m.%Y') if rec.date_from else ''
            to = rec.date_to.strftime('%d.%m.%Y') if rec.date_to else ''
            rec.name = f"Фін. результати {fr} — {to}"

    @api.depends('line_ids.current_amount', 'line_ids.code')
    def _compute_net_profit(self):
        for rec in self:
            by_code = {line.code: line.current_amount for line in rec.line_ids}
            rec.net_profit = by_code.get('2350', 0.0) - by_code.get('2355', 0.0)

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
        return self.env.ref(
            'l10n_ua_accounting.action_report_pnl'
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Run: pip install xlsxwriter'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_pnl_xlsx(workbook)
        workbook.close()
        output.seek(0)

        filename = (f"Фін_результати_{self.date_from.strftime('%d.%m.%Y')}_"
                    f"{self.date_to.strftime('%d.%m.%Y')}.xlsx")
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'raw': output.getvalue(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ── Data generation ─────────────────────────────────────

    def _get_account_turnover(self, account_codes, date_from, date_to, turnover_type='credit'):
        """Net turnover of the accounts in the period (``pnl_amount``),
        without the entries that close the period through 79."""
        self.ensure_one()
        domain = [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ] + pnl_closing_move_domain(self.env, self.company_id, date_from, date_to)
        account_domain = []
        for code in account_codes:
            if account_domain:
                account_domain = ['|'] + account_domain
            account_domain.append(('account_id.code', '=like', f'{code}%'))
        if not account_domain:
            return 0.0
        groups = self.env['account.move.line']._read_group(
            domain + account_domain, [], ['debit:sum', 'credit:sum'])
        debit, credit = groups[0] if groups else (0.0, 0.0)
        return pnl_amount(turnover_type, debit or 0.0, credit or 0.0)

    def _get_oci_amount(self, account_codes, date_from, date_to):
        """credit − debit of 41 in the period, without the transfer of a
        realised revaluation surplus to 44 (it is no comprehensive income)."""
        self.ensure_one()
        MoveLine = self.env['account.move.line']
        transfers = MoveLine.search([
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from), ('date', '<=', date_to),
            ('account_id.code', '=like', '44%'),
        ]).move_id
        total = 0.0
        for code in account_codes:
            groups = MoveLine._read_group([
                ('company_id', '=', self.company_id.id),
                ('parent_state', '=', 'posted'),
                ('date', '>=', date_from), ('date', '<=', date_to),
                ('account_id.code', '=like', f'{code}%'),
                ('move_id', 'not in', transfers.ids),
            ], [], ['balance:sum'])
            total -= (groups[0][0] or 0.0) if groups else 0.0
        return total

    def _get_element_amount(self, account_codes, date_from, date_to):
        """Debit turnover of class 8: the costs as they arise, before they are
        written off to 23 or class 9."""
        self.ensure_one()
        account_domain = ['|'] * (len(account_codes) - 1) + [
            ('account_id.code', '=like', f'{c}%') for c in account_codes]
        groups = self.env['account.move.line']._read_group([
            ('company_id', '=', self.company_id.id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from), ('date', '<=', date_to),
        ] + account_domain, [], ['debit:sum'])
        return (groups[0][0] or 0.0) if groups else 0.0

    def _period_amounts(self, date_from, date_to):
        """{key: amount} of the detail rows of all sections for a period."""
        amounts = {}
        if not (date_from and date_to):
            return amounts
        for seq, key, name, code, line_type, acct_codes, turnover in PNL_LINES:
            if line_type == 'detail' and acct_codes:
                amounts[key] = self._get_account_turnover(
                    pnl_prefixes(acct_codes), date_from, date_to, turnover)
        for seq, key, name, code, line_type, acct_codes in PNL_EXTRA_LINES:
            if line_type == 'oci' and acct_codes:
                amounts[key] = self._get_oci_amount(pnl_prefixes(acct_codes), date_from, date_to)
            elif line_type == 'element':
                amounts[key] = self._get_element_amount(pnl_prefixes(acct_codes), date_from, date_to)
        return amounts

    def _all_rows(self):
        """(sequence, key, name, code, line_type, account_codes, turnover_type)
        of every row of the form, in print order, with the loss twins."""
        rows = [PNL_SECTION_I]
        for row in PNL_LINES:
            seq, key, name, code, line_type, acct, turnover = row
            if code in PNL_MANUAL_CODES:
                row = (seq, key, name, code, 'manual', acct, turnover)
            rows.append(row)
            if code in PNL_LOSS_CODES:
                loss_code, loss_name = PNL_LOSS_CODES[code]
                rows.append((seq + 1, key + '_loss', loss_name, loss_code, 'loss', '', ''))
        rows += [(seq, key, name, code, line_type, acct, '')
                 for seq, key, name, code, line_type, acct in PNL_EXTRA_LINES]
        return rows

    def _generate_lines(self):
        """Generate report lines from account.move.line data."""
        self.ensure_one()
        current = self._period_amounts(self.date_from, self.date_to)
        previous = self._period_amounts(self.comparison_date_from, self.comparison_date_to)
        vals_list = []
        for seq, key, name, code, line_type, acct_codes, turnover in self._all_rows():
            vals_list.append({
                'report_id': self.id,
                'sequence': seq,
                'flow_key': key,
                'name': name,
                'code': code,
                'line_type': line_type,
                'account_codes': acct_codes,
                'turnover_type': turnover,
                'current_amount': current.get(key, 0.0),
                'previous_amount': previous.get(key, 0.0),
            })
        self.env['l10n_ua.pnl.report.line'].create(vals_list)
        self._recompute_totals()

    def _recompute_totals(self):
        """Fill the computed rows and the loss twins from the detail and
        manual rows (after a calculation or a row entered by hand)."""
        for rec in self:
            lines = {line.flow_key: line for line in rec.line_ids if line.flow_key}
            for field in ('current_amount', 'previous_amount'):
                base = {key: line[field] for key, line in lines.items()
                        if line.line_type in ('detail', 'manual', 'oci', 'element')}
                full = pnl_complete(base)
                for key, line in lines.items():
                    if line.line_type in ('subtotal', 'total'):
                        value = full.get(key, 0.0)
                        if line.code in PNL_LOSS_CODES:
                            twin = lines.get(key + '_loss')
                            if twin:
                                twin.with_context(l10n_ua_pnl_no_recompute=True).write(
                                    {field: max(-value, 0.0)})
                            value = max(value, 0.0)
                        line.with_context(l10n_ua_pnl_no_recompute=True).write({field: value})

    def _xml_values(self):
        """{'R2000G3': 1234, …} for J0900207: whole hryvnias (DGdecimal0),
        2610–2650 with kopecks (DGdecimal2). Expense and loss rows are
        positive, as printed in parentheses. Empty cells are left out."""
        self.ensure_one()
        values = {}
        for line in self.line_ids.filtered('code'):
            for field, graph in (('current_amount', 3), ('previous_amount', 4)):
                amount = line[field]
                amount = round(amount, 2) if line.code in PNL_DECIMAL2_CODES else round(amount)
                if amount:
                    values[f'R{line.code}G{graph}'] = amount
        return values


    def _write_pnl_xlsx(self, workbook):
        """Write P&L data to an xlsxwriter workbook."""
        worksheet = workbook.add_worksheet('Фін. результати')

        title_fmt = workbook.add_format({'bold': True, 'font_size': 14, 'align': 'center'})
        subtitle_fmt = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'center'})
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
        })
        line_fmt = workbook.add_format({'border': 1})
        code_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        subtotal_fmt = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#D9E2F3'})
        subtotal_code_fmt = workbook.add_format({'bold': True, 'border': 1, 'align': 'center', 'bg_color': '#D9E2F3'})
        subtotal_money_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00', 'border': 1, 'bg_color': '#D9E2F3'})
        total_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'border': 2})
        total_code_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'border': 2, 'align': 'center'})
        total_money_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'num_format': '#,##0.00', 'border': 2})

        worksheet.set_column('A:A', 55)
        worksheet.set_column('B:B', 12)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:D', 20)

        row = 0
        worksheet.merge_range(row, 0, row, 3, 'Звіт про фінансові результати', title_fmt)
        row += 1
        period_str = f"за {self.date_from.strftime('%d.%m.%Y')} — {self.date_to.strftime('%d.%m.%Y')}"
        worksheet.merge_range(row, 0, row, 3, period_str, subtitle_fmt)
        row += 1
        worksheet.merge_range(row, 0, row, 3, self.company_id.name, subtitle_fmt)
        row += 2

        comp_label = 'За аналогічний період'
        if self.comparison_date_from and self.comparison_date_to:
            comp_label = (f"За {self.comparison_date_from.strftime('%d.%m.%Y')} — "
                          f"{self.comparison_date_to.strftime('%d.%m.%Y')}")

        worksheet.write(row, 0, 'Стаття', header_fmt)
        worksheet.write(row, 1, 'Код рядка', header_fmt)
        worksheet.write(row, 2, 'За звітний період', header_fmt)
        worksheet.write(row, 3, comp_label, header_fmt)
        row += 1

        for line in self.line_ids.sorted('sequence'):
            if line.line_type == 'section':
                worksheet.merge_range(row, 0, row, 3, line.name, subtotal_fmt)
            elif line.line_type == 'total':
                worksheet.write(row, 0, line.name, total_fmt)
                worksheet.write(row, 1, line.code, total_code_fmt)
                worksheet.write(row, 2, line.current_amount, total_money_fmt)
                worksheet.write(row, 3, line.previous_amount, total_money_fmt)
            elif line.line_type in ('subtotal', 'loss'):
                worksheet.write(row, 0, line.name, subtotal_fmt)
                worksheet.write(row, 1, line.code, subtotal_code_fmt)
                worksheet.write(row, 2, line.current_amount, subtotal_money_fmt)
                worksheet.write(row, 3, line.previous_amount, subtotal_money_fmt)
            else:
                worksheet.write(row, 0, line.name, line_fmt)
                worksheet.write(row, 1, line.code, code_fmt)
                worksheet.write(row, 2, line.current_amount, money_fmt)
                worksheet.write(row, 3, line.previous_amount, money_fmt)
            row += 1


class L10nUaPnlReportLine(models.Model):
    _name = 'l10n_ua.pnl.report.line'
    _description = 'P&L Report Line'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.pnl.report',
        string='Report',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Line Name')
    code = fields.Char(string='Row Code')
    flow_key = fields.Char(string='Row Key')
    line_type = fields.Selection(
        selection=[
            ('section', 'Section Title'),
            ('detail', 'Detail'),
            ('manual', 'Entered by Hand'),
            ('subtotal', 'Subtotal'),
            ('loss', 'Loss'),
            ('total', 'Total'),
            ('oci', 'Other Comprehensive Income'),
            ('element', 'Element of Operating Expenses'),
        ],
        string='Line Type',
        default='detail',
    )
    account_codes = fields.Char(
        string='Account Codes',
        help='Comma-separated account code prefixes used to compute this line',
    )
    turnover_type = fields.Char(string='Turnover Type')
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

    def write(self, vals):
        if not self.env.context.get('l10n_ua_pnl_no_recompute') and (
                'current_amount' in vals or 'previous_amount' in vals):
            if self.filtered(lambda l: l.report_id.state != 'draft'):
                raise UserError(_('A confirmed report cannot be changed. Set it back to draft first.'))
            if self.filtered(lambda l: l.line_type != 'manual'):
                raise UserError(_(
                    'Only the rows 2305, 2455 and 2600–2650 are entered by hand; the other '
                    'rows come from the ledger. Recalculate the report instead.'))
            res = super().write(vals)
            self.report_id._recompute_totals()
            return res
        return super().write(vals)

    def action_view_move_lines(self):
        """Drill-down: open journal items that compose this line."""
        self.ensure_one()
        if not self.account_codes or self.line_type not in ('detail', 'oci', 'element'):
            return
        codes = [c.strip() for c in self.account_codes.split(',') if c.strip()]
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.report_id.company_id.id),
            ('date', '>=', self.report_id.date_from),
            ('date', '<=', self.report_id.date_to),
        ]
        account_domain = []
        for code in codes:
            if account_domain:
                account_domain = ['|'] + account_domain
            account_domain.append(('account_id.code', '=like', f'{code}%'))
        domain.extend(account_domain)
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} ({self.code})',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
        }
