"""Ukrainian Cash Flow Statement (Звіт про рух грошових коштів, Форма №3).

Форма № 3 (прямий метод) і № 3-н (непрямий метод) за НП(С)БО 1 (наказ
Мінфіну № 73 від 07.02.2013, ред. від 23.12.2025). Коди рядків — коди бланка
й елементів XML J0900904 / J0901602.

Прямий метод. Рух коштів класифікується не за самим грошовим рахунком, а за
**кореспондуючим**: запис Дт 311 Кт 361 — це надходження від реалізації,
Дт 311 Кт 601 — отримання позики, хоча грошова сторона в обох однакова. Тому
звіт читає проводки з грошових рахунків і розподіляє суму по контр-рядках
кожної проводки.

Непрямий метод (Ф3-н). Розділи II і III ті самі, що й у прямому. Розділ I
починається з фінансового результату до оподаткування (рядок 2290/2295 Ф2) і
коригує його на амортизацію (кредитовий оборот 13), зміну забезпечень (47),
зміну оборотних активів і поточних зобов'язань (рядки Ф1). Що лишається між
цим і фактичним операційним рухом коштів — продаж необоротних активів, курсові
різниці, інші негрошові операції — потрапляє в рядок 3520 «збиток (прибуток)
від неопераційної діяльності та інших негрошових операцій», тож 3195 однаковий
в обох методах.
"""

import io
from collections import defaultdict

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .l10n_ua_balance_report import BALANCE_LINES
from .l10n_ua_fin_rounding import format_units, round_units, to_thousands
from .l10n_ua_pnl_report import pnl_complete


# Рахунки, що формують «гроші та їх еквіваленти» — той самий набір, що й
# рядок 1165 Балансу, аби Ф№1 і Ф№3 сходилися по залишку. 35 «Поточні
# фінансові інвестиції» — рядок 1160, тож рух по ньому інвестиційний.
CASH_ACCOUNT_CODES = ('30', '31', '33')

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
    ('inv_in_noncurrent', 'in', ('10', '11', '12', '16')),
    ('inv_in_interest', 'in', ('373',)),
    ('inv_in_dividends', 'in', ('72',)),
    ('inv_out_financial', 'out', ('14', '35')),
    ('inv_out_noncurrent', 'out', ('15', '10', '11', '12', '16')),
    # --- Фінансова діяльність ---
    ('fin_in_equity', 'in', ('40', '42', '46')),
    ('fin_in_loans', 'in', ('50', '60')),
    ('fin_out_buyback', 'out', ('45',)),
    ('fin_out_loans', 'out', ('50', '60')),
    ('fin_out_dividends', 'out', ('671',)),
    ('fin_out_other', 'out', ('672',)),
    # --- Операційна діяльність ---
    ('op_in_sales', 'in', ('36', '70', '681')),
    ('op_in_taxes', 'in', ('64',)),
    ('op_in_targeted', 'in', ('48',)),
    ('op_out_goods', 'out', ('63', '371')),
    ('op_out_wages', 'out', ('66',)),
    ('op_out_social', 'out', ('65',)),
    ('op_out_taxes', 'out', ('64',)),
]

# Додаткові статті 3116–3118 (Додаток 3): частини рядка 3115 за субрахунками
# 641 плану рахунків Odoo (ua_psbo): 6413 податок на прибуток, 6412 ПДВ.
# Вони не входять у підсумки й друкуються лише із сумою.
CASHFLOW_TAX_PARTS = [
    ('op_out_taxes_profit', ('6413',)),
    ('op_out_taxes_vat', ('6412',)),
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
    (81, 'op_out_taxes_profit', "Витрачання на оплату зобов'язань з податку на прибуток", '3116', OPERATING, 'sub'),
    (82, 'op_out_taxes_vat', "Витрачання на оплату зобов'язань з податку на додану вартість", '3117', OPERATING, 'sub'),
    (83, 'op_out_taxes_other', "Витрачання на оплату зобов'язань з інших податків і зборів", '3118', OPERATING, 'sub'),
    (90, 'op_out_other', 'Інші витрачання', '3190', OPERATING, 'detail'),
    (100, 'net_operating', 'Чистий рух коштів від операційної діяльності', '3195', OPERATING, 'subtotal'),

    (110, 'inv_in_financial', 'Надходження від реалізації фінансових інвестицій', '3200', INVESTING, 'detail'),
    (120, 'inv_in_noncurrent', 'Надходження від реалізації необоротних активів', '3205', INVESTING, 'detail'),
    (130, 'inv_in_interest', 'Надходження від отриманих відсотків', '3215', INVESTING, 'detail'),
    (132, 'inv_in_dividends', 'Надходження від отриманих дивідендів', '3220', INVESTING, 'detail'),
    (134, 'inv_in_derivatives', 'Надходження від деривативів', '3225', INVESTING, 'detail'),
    (136, 'inv_in_other', 'Інші надходження', '3250', INVESTING, 'detail'),
    (140, 'inv_out_financial', 'Витрачання на придбання фінансових інвестицій', '3255', INVESTING, 'detail'),
    (150, 'inv_out_noncurrent', 'Витрачання на придбання необоротних активів', '3260', INVESTING, 'detail'),
    (152, 'inv_out_derivatives', 'Виплати за деривативами', '3270', INVESTING, 'detail'),
    (154, 'inv_out_other', 'Інші платежі', '3290', INVESTING, 'detail'),
    (160, 'net_investing', 'Чистий рух коштів від інвестиційної діяльності', '3295', INVESTING, 'subtotal'),

    (170, 'fin_in_equity', 'Надходження від власного капіталу', '3300', FINANCING, 'detail'),
    (180, 'fin_in_loans', 'Надходження від отримання позик', '3305', FINANCING, 'detail'),
    (185, 'fin_in_other', 'Інші надходження', '3340', FINANCING, 'detail'),
    (190, 'fin_out_buyback', 'Витрачання на викуп власних акцій', '3345', FINANCING, 'detail'),
    (200, 'fin_out_loans', 'Витрачання на погашення позик', '3350', FINANCING, 'detail'),
    (210, 'fin_out_dividends', 'Витрачання на сплату дивідендів', '3355', FINANCING, 'detail'),
    (215, 'fin_out_other', 'Інші платежі', '3390', FINANCING, 'detail'),
    (220, 'net_financing', 'Чистий рух коштів від фінансової діяльності', '3395', FINANCING, 'subtotal'),

    (230, 'net_cash_flow', 'Чистий рух коштів за звітний період', '3400', False, 'subtotal'),
    (240, 'cash_start', 'Залишок коштів на початок року', '3405', False, 'detail'),
    (250, 'fx_effect', 'Вплив зміни валютних курсів на залишок коштів', '3410', False, 'detail'),
    (260, 'cash_end', 'Залишок коштів на кінець року', '3415', False, 'total'),
]

# Рядки-залишки й підсумки не збираються з проводок, а рахуються окремо, тож
# деталізації в проводки не мають. «Інші надходження/витрачання» сюди не
# входять: вони наповнюються з проводок, чий контр-рахунок не має власного
# рядка бланка, і деталізуються нарівні з рештою.
COMPUTED_KEYS = {
    'net_operating', 'net_investing', 'net_financing', 'net_cash_flow',
    'cash_start', 'fx_effect', 'cash_end',
}

# Операційний розділ Ф3-н (непрямий метод). Тип 'sub' — частина рядка, що
# не входить у підсумки (додаткові статті 3551–3567 друкуються лише із сумою).
# Суми зі знаком: «+» — графа «надходження», «−» — «видаток».
INDIRECT_OPERATING_LINES = [
    (10, 'ind_profit', 'Прибуток (збиток) від звичайної діяльності до оподаткування', '3500', OPERATING, 'detail'),
    (20, 'ind_depreciation', 'Коригування на: амортизацію необоротних активів', '3505', OPERATING, 'detail'),
    (30, 'ind_provisions', 'збільшення (зменшення) забезпечень', '3510', OPERATING, 'detail'),
    (40, 'ind_fx', 'збиток (прибуток) від нереалізованих курсових різниць', '3515', OPERATING, 'detail'),
    (50, 'ind_noncash', 'збиток (прибуток) від неопераційної діяльності та інших негрошових операцій', '3520', OPERATING, 'detail'),
    (60, 'ind_current_assets', 'Зменшення (збільшення) оборотних активів', '3550', OPERATING, 'detail'),
    (61, 'ind_inventories', 'Збільшення (зменшення) запасів', '3551', OPERATING, 'sub'),
    (62, 'ind_bio', 'Збільшення (зменшення) поточних біологічних активів', '3552', OPERATING, 'sub'),
    (63, 'ind_receivables', 'Збільшення (зменшення) дебіторської заборгованості за продукцію, товари, роботи, послуги', '3553', OPERATING, 'sub'),
    (64, 'ind_other_receivables', 'Зменшення (збільшення) іншої поточної дебіторської заборгованості', '3554', OPERATING, 'sub'),
    (66, 'ind_prepaid', 'Зменшення (збільшення) витрат майбутніх періодів', '3556', OPERATING, 'sub'),
    (67, 'ind_other_assets', 'Зменшення (збільшення) інших оборотних активів', '3557', OPERATING, 'sub'),
    (70, 'ind_current_liabilities', "Збільшення (зменшення) поточних зобов'язань", '3560', OPERATING, 'detail'),
    (71, 'ind_payables', 'Збільшення (зменшення) поточної кредиторської заборгованості за товари, роботи, послуги', '3561', OPERATING, 'sub'),
    (72, 'ind_payables_budget', 'Збільшення (зменшення) поточної кредиторської заборгованості за розрахунками з бюджетом', '3562', OPERATING, 'sub'),
    (73, 'ind_payables_insurance', 'Збільшення (зменшення) поточної кредиторської заборгованості за розрахунками зі страхування', '3563', OPERATING, 'sub'),
    (74, 'ind_payables_wages', 'Збільшення (зменшення) поточної кредиторської заборгованості за розрахунками з оплати праці', '3564', OPERATING, 'sub'),
    (76, 'ind_deferred_income', 'Збільшення (зменшення) доходів майбутніх періодів', '3566', OPERATING, 'sub'),
    (77, 'ind_other_liabilities', "Збільшення (зменшення) інших поточних зобов'язань", '3567', OPERATING, 'sub'),
    (80, 'ind_operating_cash', 'Грошові кошти від операційної діяльності', '3570', OPERATING, 'subtotal'),
    (90, 'ind_tax_paid', 'Сплачений податок на прибуток', '3580', OPERATING, 'detail'),
    (100, 'net_operating', 'Чистий рух коштів від операційної діяльності', '3195', OPERATING, 'subtotal'),
]

# Частини 3550/3560: рядки Ф1, з яких складаються (ключ, коди рядків Ф1).
# Позики (1600, 1610) — фінансова діяльність, забезпечення (1660) — рядок 3510.
INDIRECT_ASSET_PARTS = [
    ('ind_inventories', ('1100',)),
    ('ind_bio', ('1110',)),
    ('ind_receivables', ('1125',)),
    ('ind_other_receivables', ('1120', '1130', '1135', '1155')),
    ('ind_prepaid', ('1170',)),
    ('ind_other_assets', ('1190',)),
]
INDIRECT_LIABILITY_PARTS = [
    ('ind_payables', ('1615',)),
    ('ind_payables_budget', ('1620',)),
    ('ind_payables_insurance', ('1625',)),
    ('ind_payables_wages', ('1630',)),
    ('ind_deferred_income', ('1665',)),
    ('ind_other_liabilities', ('1605', '1635', '1690')),
]
INDIRECT_SUB_KEYS = frozenset(
    key for key, _codes in INDIRECT_ASSET_PARTS + INDIRECT_LIABILITY_PARTS)

# Рядки Ф3-н рахуються з Ф1/Ф2, а не з проводок рахунків грошей: без деталізації.
COMPUTED_KEYS |= {line[1] for line in INDIRECT_OPERATING_LINES} | {'op_out_taxes_other'}

SECTION_SIGNS = {
    OPERATING: {
        'in': ('op_in_sales', 'op_in_taxes', 'op_in_targeted', 'op_in_other'),
        'out': ('op_out_goods', 'op_out_wages', 'op_out_social',
                'op_out_taxes', 'op_out_other'),
    },
    INVESTING: {
        'in': ('inv_in_financial', 'inv_in_noncurrent', 'inv_in_interest',
               'inv_in_dividends', 'inv_in_derivatives', 'inv_in_other'),
        'out': ('inv_out_financial', 'inv_out_noncurrent', 'inv_out_derivatives',
                'inv_out_other'),
    },
    FINANCING: {
        'in': ('fin_in_equity', 'fin_in_loans', 'fin_in_other'),
        'out': ('fin_out_buyback', 'fin_out_loans', 'fin_out_dividends', 'fin_out_other'),
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
) | {'op_out_taxes_profit', 'op_out_taxes_vat', 'op_out_taxes_other'}

# Additional articles (Додаток 3), printed only with an amount
CASHFLOW_ADDITIONAL_CODES = (
    '3116', '3117', '3118', '3551', '3552', '3553', '3554', '3556', '3557',
    '3561', '3562', '3563', '3564', '3566', '3567')


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
    method = fields.Selection(
        [('direct', 'Direct (Form No.3)'), ('indirect', 'Indirect (Form No.3-n)')],
        string='Method', required=True, default='direct', tracking=True,
        help='Direct: cash receipts and payments by their counterpart account. '
             'Indirect: the result before tax adjusted for depreciation, '
             'provisions and the change of current assets and liabilities.',
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

    @api.depends('date_from', 'date_to', 'method')
    def _compute_name(self):
        for rec in self:
            fr = rec.date_from.strftime('%d.%m.%Y') if rec.date_from else ''
            to = rec.date_to.strftime('%d.%m.%Y') if rec.date_to else ''
            suffix = ' (непрямий метод)' if rec.method == 'indirect' else ''
            rec.name = f"Рух грошових коштів {fr} — {to}{suffix}"

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
            'raw': output.getvalue(),
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
                if key == 'op_out_taxes':
                    part = self._tax_part(line.account_id)
                    if part:
                        amounts[part] += abs(contribution)
        return amounts

    @api.model
    def _tax_part(self, account):
        """Key of the additional article 3116/3117 a tax payment goes to."""
        code = account.code or ''
        for key, prefixes in CASHFLOW_TAX_PARTS:
            if code.startswith(prefixes):
                return key
        return None

    def _period_amounts(self, date_from, date_to):
        """Повний набір сум Ф№3 за період, разом із підсумками й залишками."""
        self.ensure_one()
        amounts = defaultdict(float, self._collect_flows(date_from, date_to))

        for section, directions in SECTION_SIGNS.items():
            inflow = sum(amounts.get(key, 0.0) for key in directions['in'])
            outflow = sum(amounts.get(key, 0.0) for key in directions['out'])
            amounts[f'net_{section}'] = inflow - outflow

        amounts['op_out_taxes_other'] = (
            amounts['op_out_taxes'] - amounts['op_out_taxes_profit'] - amounts['op_out_taxes_vat'])
        if self.method == 'indirect':
            amounts.update(self._indirect_amounts(date_from, date_to, amounts))

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

    def _indirect_amounts(self, date_from, date_to, flows):
        """Signed amounts of the operating section of Ф3-н («+» надходження,
        «−» видаток); 3195 is the operating cash flow of the direct method."""
        self.ensure_one()
        company = self.company_id
        result = {}
        pnl = self.env['l10n_ua.pnl.report'].new({'company_id': company.id})
        result['ind_profit'] = pnl_complete(
            pnl._period_amounts(date_from, date_to))['profit_before_tax']

        MoveLine = self.env['account.move.line']
        base = [('company_id', '=', company.id), ('parent_state', '=', 'posted')]

        def turnover(prefix, domain):
            groups = MoveLine._read_group(
                base + domain + [('account_id.code', '=like', f'{prefix}%')],
                [], ['debit:sum', 'credit:sum'])
            return (groups[0][0] or 0.0, groups[0][1] or 0.0) if groups else (0.0, 0.0)

        period = [('date', '>=', date_from), ('date', '<=', date_to)]
        result['ind_depreciation'] = turnover('13', period)[1]
        debit, credit = turnover('47', period)
        result['ind_provisions'] = credit - debit
        result['ind_fx'] = 0.0

        balance = self.env['l10n_ua.balance.report'].new({'company_id': company.id})
        start, _unmapped = balance._get_row_amounts(fields.Date.subtract(date_from, days=1))
        end, _unmapped = balance._get_row_amounts(date_to)
        key_of = {line[3]: line[1] for line in BALANCE_LINES if line[3]}

        def change(codes):
            return sum(end.get(key_of[c], 0.0) - start.get(key_of[c], 0.0) for c in codes)

        result['ind_current_assets'] = result['ind_current_liabilities'] = 0.0
        for key, codes in INDIRECT_ASSET_PARTS:
            result[key] = -change(codes)
            result['ind_current_assets'] += result[key]
        for key, codes in INDIRECT_LIABILITY_PARTS:
            result[key] = change(codes)
            result['ind_current_liabilities'] += result[key]

        result['ind_tax_paid'] = -flows.get('op_out_taxes_profit', 0.0)
        result['ind_operating_cash'] = flows['net_operating'] - result['ind_tax_paid']
        result['ind_noncash'] = result['ind_operating_cash'] - sum(result[k] for k in (
            'ind_profit', 'ind_depreciation', 'ind_provisions', 'ind_fx',
            'ind_current_assets', 'ind_current_liabilities'))
        return result

    def _form_lines(self):
        """Rows of the form for the report's method."""
        self.ensure_one()
        if self.method == 'indirect':
            return INDIRECT_OPERATING_LINES + [
                line for line in CASHFLOW_LINES if line[4] != OPERATING]
        return CASHFLOW_LINES

    def _generate_lines(self):
        self.ensure_one()
        current = self._period_amounts(self.date_from, self.date_to)
        previous = defaultdict(float)
        if self.comparison_date_from and self.comparison_date_to:
            previous = self._period_amounts(
                self.comparison_date_from, self.comparison_date_to)

        currency = self.company_id.currency_id
        vals_list = []
        for seq, key, name, code, section, line_type in self._form_lines():
            if (code in CASHFLOW_ADDITIONAL_CODES
                    and currency.is_zero(current.get(key, 0.0))
                    and currency.is_zero(previous.get(key, 0.0))):
                continue
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

    @api.model
    def _split_amount(self, line, amount):
        """(надходження, видаток) of a row of Ф3-н: an outflow row of
        sections II–III is a payment, any other row goes by its sign."""
        if line.flow_key in OUTFLOW_KEYS:
            return 0.0, amount
        return (amount, 0.0) if amount >= 0 else (0.0, -amount)

    def _form_values(self):
        """{code: (current, previous)} in thousands of hryvnias without
        decimals, signed as the stored lines. Rows are rounded; the sections,
        3400 and 3410 are added up from them, so that 3405 + 3400 + 3410 =
        3415 on the form. In Ф3-н 3550/3560 are the sums of their parts when
        they have any, and 3520 takes what keeps 3195 equal to the direct
        method: Ф3-н takes 3195 as the sum of the rounded rows of the direct
        method too (see _direct_operating_net)."""
        self.ensure_one()
        lines = self.line_ids.filtered('flow_key')
        columns = []
        periods = ((self.date_from, self.date_to),
                   (self.comparison_date_from, self.comparison_date_to))
        for field, (date_from, date_to) in zip(('current_amount', 'previous_amount'), periods):
            v = {line.flow_key: to_thousands(line[field]) for line in lines}
            if self.method == 'indirect' and 'net_operating' in v:
                stored = sum(lines.filtered(lambda l: l.flow_key == 'net_operating').mapped(field))
                v['net_operating'] = self._direct_operating_net(date_from, date_to, stored)
            nets = {}
            for section, directions in SECTION_SIGNS.items():
                if section == OPERATING and self.method == 'indirect':
                    continue
                inflow = sum(v.get(k, 0.0) for k in directions['in'])
                outflow = sum(v.get(k, 0.0) for k in directions['out'])
                nets[section] = round_units(inflow - outflow)
                v[f'net_{section}'] = nets[section]
            if self.method == 'indirect':
                for total, parts in (('ind_current_assets', INDIRECT_ASSET_PARTS),
                                     ('ind_current_liabilities', INDIRECT_LIABILITY_PARTS)):
                    keys = [k for k, _codes in parts if k in v]
                    if keys:
                        v[total] = round_units(sum(v[k] for k in keys))
                v['ind_operating_cash'] = round_units(v.get('net_operating', 0.0) - v.get('ind_tax_paid', 0.0))
                v['ind_noncash'] = round_units(v['ind_operating_cash'] - sum(v.get(k, 0.0) for k in (
                    'ind_profit', 'ind_depreciation', 'ind_provisions', 'ind_fx',
                    'ind_current_assets', 'ind_current_liabilities')))
                nets[OPERATING] = v.get('net_operating', 0.0)
            v['net_cash_flow'] = round_units(sum(nets.values()))
            v['fx_effect'] = round_units(v.get('cash_end', 0.0) - v.get('cash_start', 0.0) - v['net_cash_flow'])
            columns.append(v)
        return {line.code: (columns[0].get(line.flow_key, 0.0), columns[1].get(line.flow_key, 0.0))
                for line in lines if line.code}

    def _direct_operating_net(self, date_from, date_to, stored):
        """3195 of Ф3-н in thousands, as the direct method prints it: the sum
        of the rounded rows of section I. Ф3-н does not store those rows, so
        they are read again from the ledger; if the ledger no longer gives the
        stored 3195 (moves changed after the report was made), the stored
        amount is rounded as it is."""
        self.ensure_one()
        flows = self._collect_flows(date_from, date_to)
        signs = SECTION_SIGNS[OPERATING]
        inflow = [flows.get(k, 0.0) for k in signs['in']]
        outflow = [flows.get(k, 0.0) for k in signs['out']]
        if not self.company_id.currency_id.is_zero(sum(inflow) - sum(outflow) - stored):
            return to_thousands(stored)
        return round_units(sum(map(to_thousands, inflow)) - sum(map(to_thousands, outflow)))

    @api.model
    def _ua_fmt(self, amount):
        return format_units(amount, parentheses=False)

    @api.model
    def _ua_paren(self, amount):
        """A payment of the direct form: in parentheses, «–» when nothing."""
        return f'({format_units(amount)})' if amount else '–'

    def _xml_values(self):
        """{'R3000G3': 1234, …} for J0900904 (direct: G3 звітний, G4
        попередній; payments positive) or J0901602 (indirect: G3/G4
        надходження/видаток звітного періоду, G5/G6 — попереднього).
        Thousands without decimals; empty cells are left out."""
        self.ensure_one()
        values = {}
        form = self._form_values()
        for line in self.line_ids.filtered('code'):
            current, previous = form.get(line.code, (0.0, 0.0))
            if self.method == 'indirect':
                cells = list(zip((3, 4), self._split_amount(line, current))) + \
                    list(zip((5, 6), self._split_amount(line, previous)))
            else:
                cells = [(3, current), (4, previous)]
            for graph, amount in cells:
                if amount:
                    values[f'R{line.code}G{graph}'] = int(amount)
        return values

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
        method = 'за непрямим методом' if self.method == 'indirect' else 'за прямим методом'
        worksheet.merge_range(row, 0, row, 3, f'Звіт про рух грошових коштів ({method})', title_fmt)
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
            ('sub', 'Including (not in totals)'),
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
                key = report._classify_counterpart(line.account_id, direction)
                if key == self.flow_key or (
                        key == 'op_out_taxes' and report._tax_part(line.account_id) == self.flow_key):
                    matched |= line
        return {
            'type': 'ir.actions.act_window',
            'name': f'{self.name} ({self.code})',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', matched.ids)],
        }
