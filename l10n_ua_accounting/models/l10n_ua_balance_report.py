"""Ukrainian Balance Sheet (Баланс, Форма №1) — persistent stored report."""

import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# Line definitions: (sequence, key, name, code, section, line_type, account_codes, balance_type)
BALANCE_LINES = [
    # I. Необоротні активи
    (10, 'section_noncurrent', 'I. Необоротні активи', '', 'asset_noncurrent', 'section', '', ''),
    (11, 'intangible_assets', 'Нематеріальні активи', '1000', 'asset_noncurrent', 'detail', '12', 'balance'),
    (12, 'unfinished_capex', 'Незавершені капітальні інвестиції', '1005', 'asset_noncurrent', 'detail', '15', 'balance'),
    (13, 'fixed_assets', 'Основні засоби', '1010', 'asset_noncurrent', 'detail', '10,11', 'balance'),
    (14, 'investment_property', 'Інвестиційна нерухомість', '1015', 'asset_noncurrent', 'detail', '100', 'balance'),
    (15, 'long_term_receivables', 'Довгострокова дебіторська заборгованість', '1040', 'asset_noncurrent', 'detail', '18', 'balance'),
    (16, 'deferred_tax_assets', 'Відстрочені податкові активи', '1045', 'asset_noncurrent', 'detail', '17', 'balance'),
    (19, 'subtotal_noncurrent', 'Усього за розділом I', '1095', 'asset_noncurrent', 'subtotal', '', ''),

    # II. Оборотні активи
    (20, 'section_current', 'II. Оборотні активи', '', 'asset_current', 'section', '', ''),
    (21, 'inventories', 'Запаси', '1100', 'asset_current', 'detail', '20,21,22,23,24,25,26,27,28', 'balance'),
    (22, 'receivables_goods', 'Дебіторська заборгованість за товари', '1125', 'asset_current', 'detail', '36', 'balance'),
    (23, 'receivables_budget', 'Дебіторська заборгованість за розрахунками з бюджетом', '1135', 'asset_current', 'detail', '641,642', 'balance'),
    (24, 'other_current_receivables', 'Інша поточна дебіторська заборгованість', '1155', 'asset_current', 'detail', '37,63', 'balance'),
    (25, 'cash', 'Гроші та їх еквіваленти', '1165', 'asset_current', 'detail', '30,31,33,35', 'balance'),
    (26, 'prepaid_expenses', 'Витрати майбутніх періодів', '1170', 'asset_current', 'detail', '39', 'balance'),
    (29, 'subtotal_current', 'Усього за розділом II', '1195', 'asset_current', 'subtotal', '', ''),

    (30, 'total_assets', 'БАЛАНС', '1300', '', 'total', '', ''),

    # I. Власний капітал
    (40, 'section_equity', 'I. Власний капітал', '', 'equity', 'section', '', ''),
    (41, 'registered_capital', 'Зареєстрований капітал', '1400', 'equity', 'detail', '40', 'balance'),
    (42, 'additional_capital', 'Додатковий капітал', '1410', 'equity', 'detail', '41,42', 'balance'),
    (43, 'reserve_capital', 'Резервний капітал', '1415', 'equity', 'detail', '43', 'balance'),
    (44, 'retained_earnings', 'Нерозподілений прибуток (непокритий збиток)', '1420', 'equity', 'detail', '44', 'balance_signed'),
    (49, 'subtotal_equity', 'Усього за розділом I', '1495', 'equity', 'subtotal', '', ''),

    # II. Довгострокові зобов'язання
    (50, 'section_lt_liab', "II. Довгострокові зобов'язання", '', 'liability_longterm', 'section', '', ''),
    (51, 'long_term_loans', 'Довгострокові кредити банків', '1510', 'liability_longterm', 'detail', '50', 'balance'),
    (52, 'long_term_liabilities', "Інші довгострокові зобов'язання", '1515', 'liability_longterm', 'detail', '51,52,53,54,55', 'balance'),
    (59, 'subtotal_lt_liab', 'Усього за розділом II', '1595', 'liability_longterm', 'subtotal', '', ''),

    # III. Поточні зобов'язання
    (60, 'section_ct_liab', "III. Поточні зобов'язання", '', 'liability_current', 'section', '', ''),
    (61, 'short_term_loans', 'Короткострокові кредити банків', '1600', 'liability_current', 'detail', '60', 'balance'),
    (62, 'payables_goods', 'Кредиторська заборгованість за товари', '1615', 'liability_current', 'detail', '63', 'balance'),
    (63, 'payables_budget', "Поточні зобов'язання за розрахунками з бюджетом", '1620', 'liability_current', 'detail', '641,642', 'balance'),
    (64, 'payables_insurance', "Поточні зобов'язання зі страхування", '1625', 'liability_current', 'detail', '65', 'balance'),
    (65, 'payables_wages', "Поточні зобов'язання з оплати праці", '1630', 'liability_current', 'detail', '66', 'balance'),
    (66, 'other_current_liabilities', "Інші поточні зобов'язання", '1690', 'liability_current', 'detail', '67,68,69', 'balance'),
    (69, 'subtotal_ct_liab', 'Усього за розділом III', '1695', 'liability_current', 'subtotal', '', ''),

    (70, 'total_liabilities', 'БАЛАНС', '1900', '', 'total', '', ''),
]


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
            'datas': base64.b64encode(output.read()).decode(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ── Data generation ─────────────────────────────────────

    def _get_account_balance(self, account_codes, date):
        """Get balance for accounts matching codes at a date."""
        domain = [
            ('date', '<=', date),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]
        account_domain = []
        for code in account_codes:
            if account_domain:
                account_domain = ['|'] + account_domain
            account_domain.append(('account_id.code', '=like', f'{code}%'))
        if account_domain:
            domain.extend(account_domain)
        lines = self.env['account.move.line'].search(domain)
        return sum(lines.mapped('balance'))

    def _generate_lines(self):
        """Generate report lines from account.move.line data."""
        self.ensure_one()
        date_end = self.date_to
        date_comp = self.comparison_date or fields.Date.from_string(
            f'{self.date_to.year - 1}-12-31'
        )

        # Compute detail amounts
        amounts = {}
        for seq, key, name, code, section, line_type, acct_codes, bal_type in BALANCE_LINES:
            if line_type == 'detail' and acct_codes:
                codes = [c.strip() for c in acct_codes.split(',')]
                cur = self._get_account_balance(codes, date_end)
                prev = self._get_account_balance(codes, date_comp)
                if bal_type == 'balance_signed':
                    amounts[key] = (cur, prev)
                else:
                    amounts[key] = (abs(cur), abs(prev))

        # Compute subtotals
        section_sums = {
            'subtotal_noncurrent': ['intangible_assets', 'unfinished_capex', 'fixed_assets',
                                    'investment_property', 'long_term_receivables', 'deferred_tax_assets'],
            'subtotal_current': ['inventories', 'receivables_goods', 'receivables_budget',
                                 'other_current_receivables', 'cash', 'prepaid_expenses'],
            'subtotal_equity': ['registered_capital', 'additional_capital', 'reserve_capital', 'retained_earnings'],
            'subtotal_lt_liab': ['long_term_loans', 'long_term_liabilities'],
            'subtotal_ct_liab': ['short_term_loans', 'payables_goods', 'payables_budget',
                                 'payables_insurance', 'payables_wages', 'other_current_liabilities'],
        }
        for sub_key, detail_keys in section_sums.items():
            cur = sum(amounts.get(k, (0, 0))[0] for k in detail_keys)
            prev = sum(amounts.get(k, (0, 0))[1] for k in detail_keys)
            amounts[sub_key] = (cur, prev)

        # Totals
        amounts['total_assets'] = (
            amounts['subtotal_noncurrent'][0] + amounts['subtotal_current'][0],
            amounts['subtotal_noncurrent'][1] + amounts['subtotal_current'][1],
        )
        amounts['total_liabilities'] = (
            amounts['subtotal_equity'][0] + amounts['subtotal_lt_liab'][0] + amounts['subtotal_ct_liab'][0],
            amounts['subtotal_equity'][1] + amounts['subtotal_lt_liab'][1] + amounts['subtotal_ct_liab'][1],
        )

        # Create line records
        vals_list = []
        for seq, key, name, code, section, line_type, acct_codes, bal_type in BALANCE_LINES:
            cur, prev = amounts.get(key, (0.0, 0.0))
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
                worksheet.write(row, 0, line.name, line_fmt)
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
        ],
        string='Section',
    )
    line_type = fields.Selection(
        selection=[
            ('section', 'Section Header'),
            ('detail', 'Detail'),
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
        """Drill-down: open journal items that compose this line."""
        self.ensure_one()
        if not self.account_codes or self.line_type in ('section', 'subtotal', 'total'):
            return
        codes = [c.strip() for c in self.account_codes.split(',') if c.strip()]
        domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.report_id.company_id.id),
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
