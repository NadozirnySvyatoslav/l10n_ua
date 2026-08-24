"""Ukrainian Cash Flow Statement (Звіт про рух грошових коштів, Форма №3).

Прямий метод за НП(С)БО 1 (наказ Мінфіну № 73 від 07.02.2013). Рух коштів
класифікується не за самим грошовим рахунком, а за **кореспондуючим**: запис
Дт 311 Кт 361 — це надходження від реалізації, Дт 311 Кт 601 — отримання
позики, хоча грошова сторона в обох однакова. Тому звіт читає проводки з
грошових рахунків і розподіляє суму по контр-рядках кожної проводки.
"""

import base64
import io
from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


# Рахунки, що формують «гроші та їх еквіваленти» — той самий набір, що й
# рядок 1165 Балансу, аби Ф№1 і Ф№3 сходилися по залишку.
CASH_ACCOUNT_CODES = ('30', '31', '33', '35')

OPERATING = 'operating'
INVESTING = 'investing'
FINANCING = 'financing'

# Класифікація кореспондуючих рахунків. Перевіряється згори вниз, перший збіг
# виграє, тому специфічні розділи (інвестиційний, фінансовий) стоять перед
# операційним: рахунок 35 — і поточна фінінвестиція, і еквівалент коштів, а
# рахунок 64 трапляється і в надходженнях (повернення), і у витрачаннях.
# Кортеж: (ключ рядка, напрям, префікси рахунків).
CASHFLOW_CLASSIFIERS = [
    # --- Інвестиційна діяльність ---
    ('inv_in_financial', 'in', ('14', '35')),
    ('inv_in_noncurrent', 'in', ('10', '11', '12')),
    ('inv_in_interest', 'in', ('373',)),
    ('inv_out_financial', 'out', ('14', '35')),
    ('inv_out_noncurrent', 'out', ('15',)),
    # --- Фінансова діяльність ---
    ('fin_in_equity', 'in', ('40', '46')),
    ('fin_in_loans', 'in', ('50', '60')),
    ('fin_out_buyback', 'out', ('45',)),
    ('fin_out_loans', 'out', ('50', '60')),
    ('fin_out_dividends', 'out', ('67',)),
    # --- Операційна діяльність ---
    ('op_in_sales', 'in', ('36', '70', '681')),
    ('op_in_taxes', 'in', ('64',)),
    ('op_in_targeted', 'in', ('48',)),
    ('op_out_goods', 'out', ('63', '371')),
    ('op_out_wages', 'out', ('66',)),
    ('op_out_social', 'out', ('65',)),
    ('op_out_taxes', 'out', ('64',)),
]

# Рядки бланка Ф№3. Кортеж:
# (послідовність, ключ, назва, код рядка, розділ, тип рядка)
CASHFLOW_LINES = [
    (10, 'op_in_sales', 'Надходження від реалізації продукції (товарів, робіт, послуг)', '3000', OPERATING, 'detail'),
    (20, 'op_in_taxes', 'Надходження від повернення податків і зборів', '3005', OPERATING, 'detail'),
    (30, 'op_in_targeted', 'Надходження від цільового фінансування', '3010', OPERATING, 'detail'),
    (40, 'op_in_other', 'Інші надходження', '3095', OPERATING, 'detail'),
    (50, 'op_out_goods', 'Витрачання на оплату товарів (робіт, послуг)', '3100', OPERATING, 'detail'),
    (60, 'op_out_wages', 'Витрачання на оплату праці', '3105', OPERATING, 'detail'),
    (70, 'op_out_social', 'Витрачання на відрахування на соціальні заходи', '3110', OPERATING, 'detail'),
    (80, 'op_out_taxes', "Витрачання на зобов'язання з податків і зборів", '3115', OPERATING, 'detail'),
    (90, 'op_out_other', 'Інші витрачання', '3190', OPERATING, 'detail'),
    (100, 'net_operating', 'Чистий рух коштів від операційної діяльності', '3195', OPERATING, 'subtotal'),

    (110, 'inv_in_financial', 'Надходження від реалізації фінансових інвестицій', '3200', INVESTING, 'detail'),
    (120, 'inv_in_noncurrent', 'Надходження від реалізації необоротних активів', '3205', INVESTING, 'detail'),
    (130, 'inv_in_interest', 'Надходження від отриманих відсотків', '3220', INVESTING, 'detail'),
    (140, 'inv_out_financial', 'Витрачання на придбання фінансових інвестицій', '3250', INVESTING, 'detail'),
    (150, 'inv_out_noncurrent', 'Витрачання на придбання необоротних активів', '3255', INVESTING, 'detail'),
    (160, 'net_investing', 'Чистий рух коштів від інвестиційної діяльності', '3295', INVESTING, 'subtotal'),

    (170, 'fin_in_equity', 'Надходження від власного капіталу', '3300', FINANCING, 'detail'),
    (180, 'fin_in_loans', 'Надходження від отримання позик', '3305', FINANCING, 'detail'),
    (190, 'fin_out_buyback', 'Витрачання на викуп власних акцій', '3350', FINANCING, 'detail'),
    (200, 'fin_out_loans', 'Витрачання на погашення позик', '3355', FINANCING, 'detail'),
    (210, 'fin_out_dividends', 'Витрачання на сплату дивідендів', '3360', FINANCING, 'detail'),
    (220, 'net_financing', 'Чистий рух коштів від фінансової діяльності', '3395', FINANCING, 'subtotal'),

    (230, 'net_cash_flow', 'Чистий рух коштів за звітний період', '3400', '', 'subtotal'),
    (240, 'cash_start', 'Залишок коштів на початок року', '3405', '', 'detail'),
    (250, 'fx_effect', 'Вплив зміни валютних курсів на залишок коштів', '3410', '', 'detail'),
    (260, 'cash_end', 'Залишок коштів на кінець року', '3415', '', 'total'),
]

# Рядки-залишки й підсумки не збираються з проводок, а рахуються окремо, тож
# деталізації в проводки не мають. «Інші надходження/витрачання» сюди не
# входять: вони наповнюються з проводок, чий контр-рахунок не має власного
# рядка бланка, і деталізуються нарівні з рештою.
COMPUTED_KEYS = {
    'net_operating', 'net_investing', 'net_financing', 'net_cash_flow',
    'cash_start', 'fx_effect', 'cash_end',
}

SECTION_SIGNS = {
    OPERATING: {
        'in': ('op_in_sales', 'op_in_taxes', 'op_in_targeted', 'op_in_other'),
        'out': ('op_out_goods', 'op_out_wages', 'op_out_social',
                'op_out_taxes', 'op_out_other'),
    },
    INVESTING: {
        'in': ('inv_in_financial', 'inv_in_noncurrent', 'inv_in_interest'),
        'out': ('inv_out_financial', 'inv_out_noncurrent'),
    },
    FINANCING: {
        'in': ('fin_in_equity', 'fin_in_loans'),
        'out': ('fin_out_buyback', 'fin_out_loans', 'fin_out_dividends'),
    },
}

SECTION_TITLES = {
    OPERATING: 'I. Рух коштів у результаті операційної діяльності',
    INVESTING: 'II. Рух коштів у результаті інвестиційної діяльності',
    FINANCING: 'III. Рух коштів у результаті фінансової діяльності',
}

# Рядки-витрачання друкуються в дужках — так само, як витрати у Ф№2.
OUTFLOW_KEYS = frozenset(
    key
    for directions in SECTION_SIGNS.values()
    for key in directions['out']
)


class L10nUaCashflowReport(models.Model):
    _name = 'l10n_ua.cashflow.report'
    _description = 'Cash Flow Statement (Form №3)'
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
        default=lambda self: fields.Date.context_today(self).replace(month=1, day=1),
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
        'l10n_ua.cashflow.report.line',
        'report_id',
        string='Lines',
    )
    net_cash_flow = fields.Monetary(
        string='Net Cash Flow',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    cash_end = fields.Monetary(
        string='Cash at End',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    note = fields.Text(string='Notes')

    @api.depends('date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            fr = rec.date_from.strftime('%d.%m.%Y') if rec.date_from else ''
            to = rec.date_to.strftime('%d.%m.%Y') if rec.date_to else ''
            rec.name = f"Рух грошових коштів {fr} — {to}"

    @api.depends('line_ids.current_amount', 'line_ids.code')
    def _compute_totals(self):
        for rec in self:
            by_code = {line.code: line.current_amount for line in rec.line_ids}
            rec.net_cash_flow = by_code.get('3400', 0.0)
            rec.cash_end = by_code.get('3415', 0.0)

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('The start date must not be after the end date.'))

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
            'l10n_ua_accounting.action_report_cashflow'
        ).report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Run: pip install xlsxwriter'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_cashflow_xlsx(workbook)
        workbook.close()
        output.seek(0)

        filename = (f"Рух_коштів_{self.date_from.strftime('%d.%m.%Y')}_"
                    f"{self.date_to.strftime('%d.%m.%Y')}.xlsx")
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

    @api.model
    def _is_cash_account(self, account):
        return account.code and account.code.startswith(CASH_ACCOUNT_CODES)

    def _cash_balance_at(self, date):
        """Залишок грошових коштів станом на кінець дня `date`."""
        self.ensure_one()
        if not date:
            return 0.0
        account_domain = []
        for code in CASH_ACCOUNT_CODES:
            if account_domain:
                account_domain = ['|'] + account_domain
            account_domain.append(('account_id.code', '=like', f'{code}%'))
        lines = self.env['account.move.line'].search([
            ('date', '<=', date),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ] + account_domain)
        return sum(lines.mapped('balance'))

    @api.model
    def _classify_counterpart(self, account, direction):
        """Ключ рядка Ф№3 для кореспондуючого рахунку і напряму руху."""
        code = account.code or ''
        for key, classifier_direction, prefixes in CASHFLOW_CLASSIFIERS:
            if classifier_direction != direction:
                continue
            if code.startswith(prefixes):
                return key
        return 'op_in_other' if direction == 'in' else 'op_out_other'

    def _collect_flows(self, date_from, date_to):
        """Розподілити рух коштів за період по ключах рядків Ф№3.

        Повертає {ключ: сума}, де суми завжди додатні: напрям уже закодовано
        в самому рядку бланка (надходження чи витрачання).
        """
        self.ensure_one()
        amounts = defaultdict(float)
        if not date_from or not date_to:
            return amounts

        cash_domain = []
        for code in CASH_ACCOUNT_CODES:
            if cash_domain:
                cash_domain = ['|'] + cash_domain
            cash_domain.append(('account_id.code', '=like', f'{code}%'))
        cash_lines = self.env['account.move.line'].search([
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ] + cash_domain)
        if not cash_lines:
            return amounts

        for move in cash_lines.move_id:
            # Контр-рядки — усе, що в проводці не є грошовим рахунком.
            # Переказ між касою і рахунком у банку контр-рядків не має і в
            # звіт не потрапляє: рух коштів усередині «грошей» — не потік.
            counterparts = move.line_ids.filtered(
                lambda line: not self._is_cash_account(line.account_id))
            for line in counterparts:
                # Внесок рядка у зміну грошей — величина, протилежна його
                # власному сальдо: Дт 311 / Кт 361 дає Кт-сальдо на 361.
                contribution = -line.balance
                if not contribution:
                    continue
                direction = 'in' if contribution > 0 else 'out'
                key = self._classify_counterpart(line.account_id, direction)
                amounts[key] += abs(contribution)
        return amounts

    def _period_amounts(self, date_from, date_to):
        """Повний набір сум Ф№3 за період, разом із підсумками й залишками."""
        self.ensure_one()
        amounts = defaultdict(float, self._collect_flows(date_from, date_to))

        for section, directions in SECTION_SIGNS.items():
            inflow = sum(amounts.get(key, 0.0) for key in directions['in'])
            outflow = sum(amounts.get(key, 0.0) for key in directions['out'])
            amounts[f'net_{section}'] = inflow - outflow

        amounts['net_cash_flow'] = (amounts['net_operating']
                                    + amounts['net_investing']
                                    + amounts['net_financing'])

        opening = self._cash_balance_at(
            fields.Date.subtract(date_from, days=1)) if date_from else 0.0
        closing = self._cash_balance_at(date_to)
        amounts['cash_start'] = opening
        amounts['cash_end'] = closing
        # Курсові різниці не проходять через контр-рахунки як рух коштів, тому
        # рядок 3410 закриває розбіжність між фактичним залишком і сумою
        # потоків — саме так його й читає бланк.
        amounts['fx_effect'] = closing - opening - amounts['net_cash_flow']
        return amounts

    def _generate_lines(self):
        self.ensure_one()
        current = self._period_amounts(self.date_from, self.date_to)
        previous = defaultdict(float)
        if self.comparison_date_from and self.comparison_date_to:
            previous = self._period_amounts(
                self.comparison_date_from, self.comparison_date_to)

        vals_list = []
        for seq, key, name, code, section, line_type in CASHFLOW_LINES:
            vals_list.append({
                'report_id': self.id,
                'sequence': seq,
                'name': name,
                'code': code,
                'section': section,
                'line_type': line_type,
                'flow_key': key,
                'current_amount': current.get(key, 0.0),
                'previous_amount': previous.get(key, 0.0),
            })
        self.env['l10n_ua.cashflow.report.line'].create(vals_list)

    # ── Хелпери друкованої форми ────────────────────────────

    @api.model
    def _section_title(self, section):
        """Римський підзаголовок розділу бланка Ф№3."""
        return SECTION_TITLES.get(section, '')

    @api.model
    def _is_outflow_line(self, line):
        """Чи друкується сума рядка в дужках (витрачання)."""
        return line.flow_key in OUTFLOW_KEYS

    # ── XLSX ────────────────────────────────────────────────

    def _write_cashflow_xlsx(self, workbook):
        worksheet = workbook.add_worksheet('Рух грошових коштів')

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

        worksheet.set_column('A:A', 60)
        worksheet.set_column('B:B', 12)
        worksheet.set_column('C:C', 20)
        worksheet.set_column('D:D', 20)

        row = 0
        worksheet.merge_range(row, 0, row, 3, 'Звіт про рух грошових коштів (за прямим методом)', title_fmt)
        row += 1
        period_str = (f"за {self.date_from.strftime('%d.%m.%Y')} — "
                      f"{self.date_to.strftime('%d.%m.%Y')}")
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
                fmts = (total_fmt, total_code_fmt, total_money_fmt)
            elif line.line_type == 'subtotal':
                fmts = (subtotal_fmt, subtotal_code_fmt, subtotal_money_fmt)
            else:
                fmts = (line_fmt, code_fmt, money_fmt)
            worksheet.write(row, 0, line.name, fmts[0])
            worksheet.write(row, 1, line.code, fmts[1])
            worksheet.write(row, 2, line.current_amount, fmts[2])
            worksheet.write(row, 3, line.previous_amount, fmts[2])
            row += 1


class L10nUaCashflowReportLine(models.Model):
    _name = 'l10n_ua.cashflow.report.line'
    _description = 'Cash Flow Statement Line'
    _order = 'sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.cashflow.report',
        string='Report',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Line Name')
    code = fields.Char(string='Row Code')
    section = fields.Selection(
        selection=[
            (OPERATING, 'Operating Activities'),
            (INVESTING, 'Investing Activities'),
            (FINANCING, 'Financing Activities'),
        ],
        string='Section',
    )
    line_type = fields.Selection(
        selection=[
            ('detail', 'Detail'),
            ('subtotal', 'Subtotal'),
            ('total', 'Total'),
        ],
        string='Line Type',
        default='detail',
    )
    flow_key = fields.Char(
        string='Flow Key',
        help='Internal key that ties the line to its classification rule.',
    )
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
        """Drill-down: проводки грошових рахунків, з яких складено рядок."""
        self.ensure_one()
        if self.flow_key in COMPUTED_KEYS:
            return False
        report = self.report_id
        cash_domain = []
        for code in CASH_ACCOUNT_CODES:
            if cash_domain:
                cash_domain = ['|'] + cash_domain
            cash_domain.append(('account_id.code', '=like', f'{code}%'))
        cash_lines = self.env['account.move.line'].search([
            ('date', '>=', report.date_from),
            ('date', '<=', report.date_to),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', report.company_id.id),
        ] + cash_domain)
        matched = self.env['account.move.line']
        for move in cash_lines.move_id:
            for line in move.line_ids:
                if report._is_cash_account(line.account_id):
                    continue
                contribution = -line.balance
                if not contribution:
                    continue
                direction = 'in' if contribution > 0 else 'out'
                if report._classify_counterpart(line.account_id, direction) == self.flow_key:
                    matched |= line
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} ({self.code})',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', matched.ids)],
        }
