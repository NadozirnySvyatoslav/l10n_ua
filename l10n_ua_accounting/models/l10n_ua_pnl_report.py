"""Ukrainian P&L Statement (Звіт про фінансові результати, Форма №2) — persistent stored report."""

import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# Line definitions: (sequence, key, name, code, line_type, account_codes, turnover_type)
# turnover_type: 'credit', 'debit', 'net', '' (for computed lines)
PNL_LINES = [
    (10, 'net_revenue', 'Чистий дохід від реалізації продукції (товарів, робіт, послуг)', '2000', 'detail', '70', 'credit'),
    (20, 'cost_of_sales', 'Собівартість реалізованої продукції (товарів, робіт, послуг)', '2050', 'detail', '90', 'debit'),
    (30, 'gross_profit', 'Валовий прибуток (збиток)', '2090', 'subtotal', '', ''),
    (40, 'other_operating_income', 'Інші операційні доходи', '2120', 'detail', '71', 'credit'),
    (50, 'administrative_expenses', 'Адміністративні витрати', '2130', 'detail', '92', 'debit'),
    (60, 'selling_expenses', 'Витрати на збут', '2150', 'detail', '93', 'debit'),
    (70, 'other_operating_expenses', 'Інші операційні витрати', '2180', 'detail', '94', 'debit'),
    (80, 'operating_profit', 'Фінансовий результат від операційної діяльності', '2190', 'subtotal', '', ''),
    (90, 'financial_income', 'Фінансові доходи', '2220', 'detail', '72,73', 'credit'),
    (100, 'financial_expenses', 'Фінансові витрати', '2250', 'detail', '95,96', 'debit'),
    (110, 'other_income', 'Інші доходи', '2240', 'detail', '74', 'credit'),
    (120, 'other_expenses', 'Інші витрати', '2270', 'detail', '97', 'debit'),
    (130, 'profit_before_tax', 'Фінансовий результат до оподаткування', '2290', 'subtotal', '', ''),
    (140, 'income_tax_expense', 'Витрати (дохід) з податку на прибуток', '2300', 'detail', '98', 'debit'),
    (150, 'net_profit', 'Чистий фінансовий результат', '2350', 'total', '', ''),
]


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

    @api.depends('line_ids.current_amount', 'line_ids.line_type')
    def _compute_net_profit(self):
        for rec in self:
            profit = 0.0
            for line in rec.line_ids:
                if line.line_type == 'total' and line.code == '2350':
                    profit = line.current_amount
            rec.net_profit = profit

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
            'datas': base64.b64encode(output.read()).decode(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ── Data generation ─────────────────────────────────────

    def _get_account_turnover(self, account_codes, date_from, date_to, turnover_type='credit'):
        """Get turnover for accounts matching codes for a period."""
        domain = [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
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
        if turnover_type == 'debit':
            return sum(lines.mapped('debit'))
        elif turnover_type == 'credit':
            return sum(lines.mapped('credit'))
        else:
            return sum(lines.mapped('credit')) - sum(lines.mapped('debit'))

    def _generate_lines(self):
        """Generate report lines from account.move.line data."""
        self.ensure_one()
        comp_from = self.comparison_date_from
        comp_to = self.comparison_date_to

        # Compute detail amounts
        amounts = {}
        for seq, key, name, code, line_type, acct_codes, turnover_type in PNL_LINES:
            if line_type == 'detail' and acct_codes:
                codes = [c.strip() for c in acct_codes.split(',')]
                cur = self._get_account_turnover(codes, self.date_from, self.date_to, turnover_type)
                prev = 0.0
                if comp_from and comp_to:
                    prev = self._get_account_turnover(codes, comp_from, comp_to, turnover_type)
                amounts[key] = (cur, prev)

        # Computed subtotals
        gp_cur = amounts['net_revenue'][0] - amounts['cost_of_sales'][0]
        gp_prev = amounts['net_revenue'][1] - amounts['cost_of_sales'][1]
        amounts['gross_profit'] = (gp_cur, gp_prev)

        op_cur = (gp_cur + amounts['other_operating_income'][0]
                  - amounts['administrative_expenses'][0]
                  - amounts['selling_expenses'][0]
                  - amounts['other_operating_expenses'][0])
        op_prev = (gp_prev + amounts['other_operating_income'][1]
                   - amounts['administrative_expenses'][1]
                   - amounts['selling_expenses'][1]
                   - amounts['other_operating_expenses'][1])
        amounts['operating_profit'] = (op_cur, op_prev)

        pbt_cur = (op_cur + amounts['financial_income'][0] - amounts['financial_expenses'][0]
                   + amounts['other_income'][0] - amounts['other_expenses'][0])
        pbt_prev = (op_prev + amounts['financial_income'][1] - amounts['financial_expenses'][1]
                    + amounts['other_income'][1] - amounts['other_expenses'][1])
        amounts['profit_before_tax'] = (pbt_cur, pbt_prev)

        np_cur = pbt_cur - amounts['income_tax_expense'][0]
        np_prev = pbt_prev - amounts['income_tax_expense'][1]
        amounts['net_profit'] = (np_cur, np_prev)

        # Create line records
        vals_list = []
        for seq, key, name, code, line_type, acct_codes, turnover_type in PNL_LINES:
            cur, prev = amounts.get(key, (0.0, 0.0))
            vals_list.append({
                'report_id': self.id,
                'sequence': seq,
                'name': name,
                'code': code,
                'line_type': line_type,
                'account_codes': acct_codes,
                'turnover_type': turnover_type,
                'current_amount': cur,
                'previous_amount': prev,
            })
        self.env['l10n_ua.pnl.report.line'].create(vals_list)

    # ── XLSX ────────────────────────────────────────────────

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
            if line.line_type == 'total':
                worksheet.write(row, 0, line.name, total_fmt)
                worksheet.write(row, 1, line.code, total_code_fmt)
                worksheet.write(row, 2, line.current_amount, total_money_fmt)
                worksheet.write(row, 3, line.previous_amount, total_money_fmt)
            elif line.line_type == 'subtotal':
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
    line_type = fields.Selection(
        selection=[
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

    def action_view_move_lines(self):
        """Drill-down: open journal items that compose this line."""
        self.ensure_one()
        if not self.account_codes or self.line_type in ('subtotal', 'total'):
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
