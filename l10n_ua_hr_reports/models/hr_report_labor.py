"""Form № 1-ПВ «Звіт із праці» (Держстат), monthly and quarterly.

Both forms are approved by наказ Держстату від 15.04.2024 № 117
(https://www.ukrstat.gov.ua/norm_doc/2024/117/117_2024.htm), in force from the
report for January 2025 (monthly) and for Q1 2025 (quarterly). The row codes,
row names and columns below are those of the forms annexed to the order
(117_mis.pdf, 117_kv.pdf). Both are due no later than the 7th day of the month
after the period and are filed only electronically with a КЕП: through the
«Кабінет респондента» of Держстат (https://statzvit.ukrstat.gov.ua) or, as
this module does, through the Електронний кабінет ДПС (hr_report_labor_xml).

Every row is a line of the report. A line computed from Odoo data can be
overridden by hand, and the override survives a recompute; a row Odoo has no
data for is a manual line from the start.
"""
import base64
import io
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round

# Contracts whose holders are not on the staff (облікового складу): civil-law
# contracts, author contracts and Diia.City gig contracts, which the law
# defines as a civil-law contract too.
NON_STAFF_CONTRACTS = ('civil', 'gig', 'author')

# Dismissals by reason (Section I of the quarterly form), by the code of
# hr.termination.reason (l10n_ua_hr_contract data).
DISMISSAL_REORGANIZATION = {'REORG', 'REDUCTION', 'LIQUID'}       # п. 1 ст. 40 КЗпП
DISMISSAL_TURNOVER = {
    'OWN', 'OWN_V', 'EARLY_EMP', 'WAR_2136_5',     # власне бажання (ст. 38, 39)
    'AGR',                                         # угода сторін (п. 1 ст. 36)
    'SYST', 'ABSENCE', 'INTOX', 'THEFT', 'GROSS',  # порушення трудової дисципліни
}

# Section III rows each wage fund group adds to.
GROUP_ROWS = {
    'basic': ('5020',),
    'allowance': ('5030', '5040'),
    'bonus': ('5030', '5050'),
    'indexation': ('5030', '5051'),
    'delay_compensation': ('5030', '5052'),
    'additional': ('5030',),
    'additional_unworked': ('5030', '5090'),
    'incentive': ('5060',),
    'material_aid': ('5060', '5070'),
    'social_benefit': ('5060', '5080'),
    'incentive_unworked': ('5060', '5090'),
    'excluded': (),
}

# (period, section, code, column, name, unit, auto, fourth quarter only)
# unit: 'kuah' тис.грн з одним десятковим знаком, 'persons' осіб, 'hours'
# люд.год, 'units' од, 'uah' грн із двома десятковими знаками.
_M, _Q = 'month', 'quarter'
ROWS = [
    (_M, '1', '1020', '1', 'Фонд оплати праці усіх працівників', 'kuah', True, False),
    (_M, '1', '1030', '1', 'Сума податку з доходів фізичних осіб, що відрахована з фонду '
                           'оплати праці усіх працівників (крім тимчасової непрацездатності)',
     'kuah', True, False),
    (_M, '1', '1040', '1', 'Середньооблікова кількість штатних працівників', 'persons', True, False),
    (_M, '1', '1060', '1', 'Кількість відпрацьованого робочого часу штатними працівниками',
     'hours', True, False),
    (_M, '1', '1070', '1', 'Фонд оплати праці штатних працівників (із ряд.1020)', 'kuah', True, False),
]
for _code, _name, _q4 in [
    ('3020', 'Кількість прийнятих штатних працівників', False),
    ('3040', 'Кількість звільнених штатних працівників', False),
    ('3050', 'Кількість звільнених штатних працівників із причини змін в організації '
             'виробництва і праці (реорганізація, скорочення кількості або штату '
             'працівників) (із ряд.3040)', False),
    ('3060', 'Кількість звільнених штатних працівників із причини плинності кадрів (за '
             'власним бажанням, за угодою сторін, порушення трудової дисципліни, ін.) '
             '(із ряд.3040)', False),
    ('3070', 'Облікова кількість штатних працівників на кінець звітного періоду', False),
    ('3080', 'Облікова кількість штатних працівників, прийнятих на умовах неповного '
             'робочого дня (тижня)', True),
    ('3090', 'Облікова кількість штатних працівників, які знаходяться у відпустці у '
             'зв’язку з вагітністю та пологами', True),
    ('3100', 'Облікова кількість штатних працівників, які знаходяться у відпустці по '
             'догляду за дитиною до досягнення нею віку, установленого чинним '
             'законодавством', True),
]:
    ROWS.append((_Q, '1', _code, '1', _name, 'persons', True, _q4))
    ROWS.append((_Q, '1', _code, '2', _name, 'persons', True, _q4))
for _code, _name in [
    ('4080', 'Кількість невідпрацьованого робочого часу через відпустки без збереження '
             'заробітної плати (на період припинення виконання робіт)'),
    ('4090', 'Кількість невідпрацьованого робочого часу через переведення на неповний '
             'робочий день (тиждень) з економічних причин'),
    ('4100', 'Кількість невідпрацьованого робочого часу через масові невиходи на роботу '
             '(страйки)'),
]:
    ROWS.append((_Q, '2', _code, '1', _name, 'hours', False, False))
    ROWS.append((_Q, '2', _code, '2', _name, 'persons', False, False))
for _code, _name in [
    ('5010', 'Фонд оплати праці штатних працівників, усього (ряд.5020 + ряд.5030 + ряд.5060)'),
    ('5020', 'Фонд основної заробітної плати'),
    ('5030', 'Фонд додаткової заробітної плати'),
    ('5040', 'Надбавки та доплати до тарифних ставок та посадових окладів (із ряд.5030)'),
    ('5050', 'Премії та винагороди, що носять систематичний характер (щомісячні, '
             'щоквартальні) (із ряд.5030)'),
    ('5051', 'Виплати, пов’язані з індексацією заробітної плати (із ряд.5030)'),
    ('5052', 'Компенсація втрати частини заробітку у зв’язку з порушенням термінів її '
             'виплати (із ряд.5030)'),
    ('5060', 'Заохочувальні та компенсаційні виплати'),
    ('5070', 'Матеріальна допомога (із ряд.5060)'),
    ('5080', 'Соціальні пільги, що мають індивідуальний характер (із ряд.5060)'),
    ('5090', 'Оплата за невідпрацьований робочий час (із ряд.5030, 5060)'),
]:
    ROWS.append((_Q, '3', _code, '1', _name, 'kuah', True, False))
for _code, _name in [
    ('7010', 'Із середньооблікової кількості штатних працівників: жінки'),
    ('7030', 'Позаштатні: зовнішні сумісники'),
    ('7040', 'Позаштатні: працюють за цивільно-правовими договорами'),
]:
    ROWS.append((_Q, '4', _code, '1', _name, 'persons', True, False))
    ROWS.append((_Q, '4', _code, '2', _name, 'kuah', True, False))
    ROWS.append((_Q, '4', _code, '3', _name, 'hours', True, False))
for _code, _name, _unit in [
    ('8010', 'Кількість укладених і зареєстрованих колективних договорів', 'units'),
    ('8020', 'Кількість штатних працівників, які охоплені колективними договорами', 'persons'),
    ('8030', 'Розмір мінімальної місячної тарифної ставки (окладу), установлений у '
             'колективному договорі', 'uah'),
    ('8040', 'Розмір мінімальної місячної тарифної ставки (окладу), установлений у '
             'галузевій угоді', 'uah'),
]:
    ROWS.append((_Q, '5', _code, '1', _name, _unit, False, True))

SECTIONS = {
    'month': {'1': 'I. Кількість працівників, робочий час і фонд оплати праці'},
    'quarter': {
        '1': 'І. Кількість штатних працівників',
        '2': 'II. Втрати робочого часу штатних працівників',
        '3': 'IІІ. Склад фонду оплати праці штатних працівників',
        '4': 'IV. Кількість і фонд оплати праці окремих категорій працівників',
        '5': 'V. Інформація про укладання колективних договорів станом на 31 грудня '
             'звітного року',
    },
}
COLUMNS = {
    ('month', '1'): {'1': 'За звітний місяць'},
    ('quarter', '1'): {'1': 'Усього', '2': 'У т.ч. жінки'},
    ('quarter', '2'): {'1': 'Люд.год', '2': 'Осіб'},
    ('quarter', '3'): {'1': 'Усього'},
    ('quarter', '4'): {'1': 'Середньооблікова кількість, осіб',
                       '2': 'Фонд оплати праці, тис.грн',
                       '3': 'Кількість відпрацьованих людиногодин'},
    ('quarter', '5'): {'1': 'Усього по підприємству'},
}
UNIT_DIGITS = {'kuah': 1, 'persons': 0, 'hours': 0, 'units': 0, 'uah': 2}

MONTHS = [
    ('1', 'January'), ('2', 'February'), ('3', 'March'),
    ('4', 'April'), ('5', 'May'), ('6', 'June'),
    ('7', 'July'), ('8', 'August'), ('9', 'September'),
    ('10', 'October'), ('11', 'November'), ('12', 'December'),
]
MONTH_NAMES_UK = {
    1: 'січень', 2: 'лютий', 3: 'березень', 4: 'квітень', 5: 'травень',
    6: 'червень', 7: 'липень', 8: 'серпень', 9: 'вересень', 10: 'жовтень',
    11: 'листопад', 12: 'грудень',
}
# «у березні» in the title of the monthly form
MONTH_NAMES_UK_LOCATIVE = {
    1: 'січні', 2: 'лютому', 3: 'березні', 4: 'квітні', 5: 'травні',
    6: 'червні', 7: 'липні', 8: 'серпні', 9: 'вересні', 10: 'жовтні',
    11: 'листопаді', 12: 'грудні',
}
QUARTER_NAMES_UK = {1: 'I квартал', 2: 'II квартал', 3: 'III квартал', 4: 'IV квартал'}


class HrReportLabor(models.Model):
    _name = 'hr.report.labor'
    _description = 'Labour Report 1-PV (State Statistics)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, period_type'

    name = fields.Char(compute='_compute_name', store=True)
    period_type = fields.Selection([
        ('month', 'Monthly'),
        ('quarter', 'Quarterly'),
    ], string='Form', required=True, default='month', tracking=True)
    year = fields.Integer(
        required=True, default=lambda self: fields.Date.today().year, tracking=True)
    month = fields.Selection(MONTHS, tracking=True)
    quarter = fields.Selection([
        ('1', 'Q1'), ('2', 'Q2'), ('3', 'Q3'), ('4', 'Q4'),
    ], tracking=True)
    date_from = fields.Date(string='Period Start', compute='_compute_period', store=True)
    date_to = fields.Date(string='Period End', compute='_compute_period', store=True)
    date_deadline = fields.Date(
        string='Filing Deadline', compute='_compute_period', store=True,
        help='No later than the 7th day of the month after the period; a deadline '
             'falling on a weekend moves to the next Monday.')
    period_key = fields.Char(compute='_compute_period', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], string='Status', default='draft', required=True, tracking=True)
    line_ids = fields.One2many('hr.report.labor.line', 'report_id', string='Rows')
    computed_on = fields.Datetime(string='Computed On', readonly=True)

    # Пояснення до розділу І (monthly form).
    headcount_change = fields.Float(
        string='Average Headcount Change, %', digits=(10, 1), readonly=True,
        help='Change of row 1040 against the monthly report of the previous month.')
    avg_wage_change = fields.Float(
        string='Average Wage Change, %', digits=(10, 1), readonly=True,
        help='Change of row 1070 / row 1040 × 1000 against the previous month.')
    explanation_headcount = fields.Text(
        string='Reason for Headcount Deviation',
        help='Required by the form when the average headcount changed by 25% or more.')
    explanation_avg_wage = fields.Text(
        string='Reason for Average Wage Deviation',
        help='Required by the form when the average wage changed by 10% or more.')
    needs_explanation = fields.Boolean(compute='_compute_needs_explanation')
    notes = fields.Text()

    _period_company_uniq = models.Constraint(
        'unique(company_id, period_key)',
        'A 1-PV report for this period already exists!',
    )

    # ------------------------------------------------------------------ period

    @api.depends('period_type', 'year', 'month', 'quarter')
    def _compute_period(self):
        for rec in self:
            if not rec.year or (rec.period_type == 'month' and not rec.month) \
                    or (rec.period_type == 'quarter' and not rec.quarter):
                rec.date_from = rec.date_to = rec.date_deadline = False
                rec.period_key = False
                continue
            if rec.period_type == 'month':
                first = last = int(rec.month)
                rec.period_key = 'M%04d-%02d' % (rec.year, first)
            else:
                last = int(rec.quarter) * 3
                first = last - 2
                rec.period_key = 'Q%04d-%s' % (rec.year, rec.quarter)
            rec.date_from = date(rec.year, first, 1)
            rec.date_to = date(rec.year, last, monthrange(rec.year, last)[1])
            deadline = rec.date_to + timedelta(days=7)
            while deadline.weekday() >= 5:
                deadline += timedelta(days=1)
            rec.date_deadline = deadline

    def _period_label(self, locative=False):
        self.ensure_one()
        if self.period_type == 'month' and self.month:
            names = MONTH_NAMES_UK_LOCATIVE if locative else MONTH_NAMES_UK
            return '%s %s р.' % (names[int(self.month)], self.year)
        if self.period_type == 'quarter' and self.quarter:
            return '%s %s р.' % (QUARTER_NAMES_UK[int(self.quarter)], self.year)
        return ''

    @api.depends('period_type', 'year', 'month', 'quarter')
    def _compute_name(self):
        for rec in self:
            form = '1-ПВ (місячна)' if rec.period_type == 'month' else '1-ПВ (квартальна)'
            label = rec._period_label()
            rec.name = '%s за %s' % (form, label) if label else '1-ПВ'

    @api.depends('headcount_change', 'avg_wage_change', 'period_type')
    def _compute_needs_explanation(self):
        for rec in self:
            rec.needs_explanation = rec.period_type == 'month' and (
                abs(rec.headcount_change) >= 25 or abs(rec.avg_wage_change) >= 10)

    @api.onchange('period_type')
    def _onchange_period_type(self):
        if self.period_type == 'month':
            self.quarter = False
        else:
            self.month = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.period_type == 'month' and not rec.month \
                    or rec.period_type == 'quarter' and not rec.quarter:
                raise UserError(_('Set the month or the quarter of the report.'))
            rec._sync_lines()
            if rec.date_deadline and rec.date_deadline >= fields.Date.context_today(rec):
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=rec.date_deadline,
                    summary=_('File %s to the State Statistics Service', rec.name),
                    user_id=self.env.user.id)
        return records

    # ------------------------------------------------------------------- lines

    def _row_defs(self):
        self.ensure_one()
        q4 = self.period_type == 'quarter' and self.quarter == '4'
        return [row for row in ROWS
                if row[0] == self.period_type and (q4 or not row[7])]

    def _sync_lines(self):
        """Make the lines match the rows of the form, keeping what was typed."""
        for rec in self:
            existing = {(line.code, line.column_no): line for line in rec.line_ids}
            wanted = set()
            vals = []
            for seq, (_p, section, code, column, name, unit, auto, _q4) in \
                    enumerate(rec._row_defs()):
                wanted.add((code, column))
                if (code, column) in existing:
                    continue
                vals.append({
                    'report_id': rec.id,
                    'sequence': seq,
                    'section': section,
                    'code': code,
                    'column_no': column,
                    'name': name,
                    'unit': unit,
                    'is_auto': auto,
                    'is_manual': not auto,
                })
            self.env['hr.report.labor.line'].create(vals)
            rec.line_ids.filtered(lambda l: (l.code, l.column_no) not in wanted).unlink()

    def _line(self, code, column='1'):
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.code == code and l.column_no == column)[:1]

    def get_value(self, code, column='1'):
        """The value of a cell as reported (override included)."""
        return self._line(code, column).value

    # ----------------------------------------------------------------- actions

    def action_compute(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft report can be recomputed.'))
            rec._sync_lines()
            raw = rec._compute_raw_values()
            for line in rec.line_ids:
                if not line.is_auto:
                    continue
                value = raw.get((line.code, line.column_no), 0.0)
                line.computed_value = line._to_form_units(value)
            # The total is the sum of its parts as reported, so that it still
            # adds up when one of them was overridden.
            total = rec._line('5010')
            if total:
                total.computed_value = sum(
                    rec.get_value(code) for code in ('5020', '5030', '5060'))
            rec._compute_deviation()
            rec.computed_on = fields.Datetime.now()
        return True

    def action_done(self):
        for rec in self:
            if not rec.computed_on:
                raise UserError(_('Compute the report before marking it as done.'))
            rec.state = 'done'
            rec.activity_feedback(['mail.mail_activity_data_todo'])
        return True

    def action_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_print(self):
        self.ensure_one()
        return self.env.ref('l10n_ua_hr_reports.action_report_hr_report_labor').report_action(self)

    def _compute_deviation(self):
        self.ensure_one()
        self.headcount_change = self.avg_wage_change = 0.0
        if self.period_type != 'month':
            return
        prev_end = self.date_from - timedelta(days=1)
        prev = self.search([
            ('company_id', '=', self.company_id.id),
            ('period_key', '=', 'M%04d-%02d' % (prev_end.year, prev_end.month)),
        ], limit=1)
        if not prev:
            return
        cur_hc, prev_hc = self.get_value('1040'), prev.get_value('1040')
        if prev_hc:
            self.headcount_change = (cur_hc - prev_hc) / prev_hc * 100
        if cur_hc and prev_hc:
            cur_wage = self.get_value('1070') / cur_hc
            prev_wage = prev.get_value('1070') / prev_hc
            if prev_wage:
                self.avg_wage_change = (cur_wage - prev_wage) / prev_wage * 100

    # ------------------------------------------------------------- computation

    def _months(self):
        """(first day, last day) of each month of the period."""
        self.ensure_one()
        result = []
        current = self.date_from
        while current <= self.date_to:
            last = date(current.year, current.month, monthrange(current.year, current.month)[1])
            result.append((current, last))
            current = last + timedelta(days=1)
        return result

    @api.model
    def _version_kind(self, version):
        """'staff', 'external' (зовнішній сумісник) or 'civil' (ЦПД)."""
        if version.contract_type_ua in NON_STAFF_CONTRACTS:
            return 'civil'
        if version.employment_type_ua == 'external':
            return 'external'
        return 'staff'

    def _long_leaves(self, date_from, date_to):
        """{employee_id: [(start, end, category)]} of the maternity and
        childcare leaves overlapping the period.

        People on these leaves stay on the payroll (облікова кількість) but are
        left out of the average headcount. The leaves come from
        l10n_ua_hr_holidays, which this module does not require: without it
        nobody is on such a leave.
        """
        if 'hr.leave' not in self.env \
                or 'ua_leave_category' not in self.env['hr.leave.type']._fields:
            return {}
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id.company_id', '=', self.company_id.id),
            ('state', '=', 'validate'),
            ('holiday_status_id.ua_leave_category', 'in', ('maternity', 'childcare')),
            ('request_date_from', '<=', date_to),
            ('request_date_to', '>=', date_from),
        ])
        result = defaultdict(list)
        for leave in leaves:
            result[leave.employee_id.id].append((
                leave.request_date_from, leave.request_date_to,
                leave.holiday_status_id.ua_leave_category))
        return result

    @api.model
    def _leave_on(self, leaves, employee, day):
        for start, end, category in leaves.get(employee.id, ()):
            if start <= day <= end:
                return category
        return False

    def _headcount_engine(self):
        return self.env['hr.report.headcount'].new({'company_id': self.company_id.id})

    def _average_headcounts(self, leaves):
        """Average headcounts of the period, by kind: the daily rates summed
        over the calendar days of each month and divided by them, and for a
        quarter the mean of its months (Інструкція зі статистики кількості
        працівників, наказ Держкомстату від 28.09.2005 № 286)."""
        engine = self._headcount_engine()
        monthly = []
        for first, last in self._months():
            sums = defaultdict(float)
            day = first
            while day <= last:
                for version, rate in engine._versions_with_rate_on_date(day):
                    kind = self._version_kind(version)
                    employee = version.employee_id
                    if kind == 'staff' and self._leave_on(leaves, employee, day):
                        continue
                    sums[kind] += rate
                    if kind == 'staff' and employee.gender == 'female':
                        sums['staff_female'] += rate
                day += timedelta(days=1)
            days = (last - first).days + 1
            monthly.append({kind: total / days for kind, total in sums.items()})
        result = defaultdict(float)
        for month in monthly:
            for kind, value in month.items():
                result[kind] += value / len(monthly)
        return result

    def _payslips(self):
        return self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'done'),
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
        ])

    def _payslip_kind(self, slip):
        version = slip.version_id or slip.employee_id.version_id
        return self._version_kind(version) if version else 'staff'

    def _payslip_figures(self):
        """Wage fund by kind and by Section III row, hours by kind, and the
        personal income tax on the wage fund other than sick pay."""
        fund = defaultdict(float)         # kind / 'staff_female' -> UAH
        rows = defaultdict(float)         # Section III row -> UAH (staff)
        hours = defaultdict(float)
        pdfo = 0.0
        for slip in self._payslips():
            kind = self._payslip_kind(slip)
            female = kind == 'staff' and slip.employee_id.gender == 'female'
            slip_fund = 0.0
            taxable_total = taxable_fund = 0.0
            for accrual in slip.accrual_ids:
                group = accrual.accrual_type_id._l10n_ua_1pv_effective_group() \
                    if accrual.accrual_type_id else 'incentive'
                in_fund = group != 'excluded'
                if accrual.is_taxable_pdfo:
                    taxable_total += accrual.amount
                    if in_fund and accrual.accrual_type_id.category != 'sick':
                        taxable_fund += accrual.amount
                if not in_fund:
                    continue
                slip_fund += accrual.amount
                if kind == 'staff':
                    for row in GROUP_ROWS[group]:
                        rows[row] += accrual.amount
            fund[kind] += slip_fund
            if female:
                fund['staff_female'] += slip_fund
            worked = (slip.worked_hours or 0.0) + (slip.overtime_hours or 0.0)
            hours[kind] += worked
            if female:
                hours['staff_female'] += worked
            if taxable_total and slip.pdfo_amount:
                # The tax of the payslip shared out over its taxable accruals:
                # the form wants it without the tax on sick pay and on what is
                # outside the wage fund.
                pdfo += slip.pdfo_amount * taxable_fund / taxable_total
        return fund, rows, hours, pdfo

    def _staff_on(self, day):
        """[(version, rate)] of the staff employed on `day`."""
        return [(version, rate)
                for version, rate in self._headcount_engine()._versions_with_rate_on_date(day)
                if self._version_kind(version) == 'staff']

    def _movements(self):
        """Hires and dismissals of staff in the period, each a set of
        (employee, date) so that the versions of one contract count once."""
        Version = self.env['hr.version'].with_context(active_test=False)
        company = [('employee_id.company_id', '=', self.company_id.id)]
        hired = {}
        for version in Version.search(company + [
                ('contract_date_start', '>=', self.date_from),
                ('contract_date_start', '<=', self.date_to)]):
            if self._version_kind(version) == 'staff':
                hired[(version.employee_id.id, version.contract_date_start)] = version
        dismissed = {}
        for version in Version.search(company + [
                ('contract_date_end', '>=', self.date_from),
                ('contract_date_end', '<=', self.date_to)],
                order='date_version desc, id desc'):
            if self._version_kind(version) != 'staff':
                continue
            key = (version.employee_id.id, version.contract_date_end)
            # The latest version is the one the dismissal reason is written on.
            if key not in dismissed or (not dismissed[key].termination_reason_ua_id
                                        and version.termination_reason_ua_id):
                dismissed[key] = version
        return hired, dismissed

    def _compute_raw_values(self):
        """{(code, column): value in natural units (UAH, persons, hours)}."""
        self.ensure_one()
        values = {}
        leaves = self._long_leaves(self.date_from, self.date_to)
        averages = self._average_headcounts(leaves)
        fund, rows, hours, pdfo = self._payslip_figures()

        if self.period_type == 'month':
            values[('1020', '1')] = fund['staff'] + fund['external'] + fund['civil']
            values[('1030', '1')] = pdfo
            values[('1040', '1')] = averages['staff']
            values[('1060', '1')] = hours['staff']
            values[('1070', '1')] = fund['staff']
            return values

        # Section I — movement and the payroll at the end of the period.
        hired, dismissed = self._movements()

        def put(code, versions):
            values[(code, '1')] = len(versions)
            values[(code, '2')] = len([v for v in versions if v.employee_id.gender == 'female'])

        put('3020', list(hired.values()))
        put('3040', list(dismissed.values()))
        put('3050', [v for v in dismissed.values()
                     if v.termination_reason_ua_id.code in DISMISSAL_REORGANIZATION])
        put('3060', [v for v in dismissed.values()
                     if v.termination_reason_ua_id.code in DISMISSAL_TURNOVER])
        on_end = self._staff_on(self.date_to)
        put('3070', [v for v, _rate in on_end])
        if self.quarter == '4':
            put('3080', [v for v, rate in on_end if rate < 1.0])
            put('3090', [v for v, _rate in on_end
                         if self._leave_on(leaves, v.employee_id, self.date_to) == 'maternity'])
            put('3100', [v for v, _rate in on_end
                         if self._leave_on(leaves, v.employee_id, self.date_to) == 'childcare'])

        # Section III — the wage fund of the staff.
        for code in ('5020', '5030', '5040', '5050', '5051', '5052',
                     '5060', '5070', '5080', '5090'):
            values[(code, '1')] = rows[code]

        # Section IV — women among the staff, external part-timers, ЦПД.
        for code, kind in (('7010', 'staff_female'), ('7030', 'external'), ('7040', 'civil')):
            values[(code, '1')] = averages[kind]
            values[(code, '2')] = fund[kind]
            values[(code, '3')] = hours[kind]
        return values

    # ------------------------------------------------------------------ export

    def _sections(self):
        """The lines of the report as the form lays them out: [{title,
        columns: [(column, label)], rows: [{code, name, cells: {column: line}}]}]."""
        self.ensure_one()
        result = []
        for section, title in SECTIONS[self.period_type].items():
            lines = self.line_ids.filtered(lambda l: l.section == section).sorted('sequence')
            if not lines:
                continue
            columns = COLUMNS[(self.period_type, section)]
            rows = []
            for line in lines:
                if not rows or rows[-1]['code'] != line.code:
                    rows.append({'code': line.code, 'name': line.name, 'cells': {}})
                rows[-1]['cells'][line.column_no] = line
            result.append({
                'title': title,
                'columns': list(columns.items()),
                'rows': rows,
            })
        return result

    def action_export_xlsx(self):
        """The rows of the form as a spreadsheet, to be keyed into the
        «Кабінет респондента»: Держстат publishes no file format for 1-ПВ."""
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('xlsxwriter is not installed. Run: pip install xlsxwriter'))
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('1-ПВ')
        bold = workbook.add_format({'bold': True})
        wrap = workbook.add_format({'text_wrap': True, 'valign': 'top'})
        head = workbook.add_format({'bold': True, 'text_wrap': True, 'border': 1})
        formats = {digits: workbook.add_format({'num_format': '0.' + '0' * digits if digits else '0'})
                   for digits in set(UNIT_DIGITS.values())}
        sheet.set_column(0, 0, 70)
        sheet.set_column(1, 1, 8)
        sheet.set_column(2, 4, 18)
        row = 0
        sheet.write(row, 0, '%s — %s' % (self.name, self.company_id.name), bold)
        row += 1
        sheet.write(row, 0, _('EDRPOU: %s', self.company_id.edrpou or ''))
        row += 2
        for section in self._sections():
            sheet.write(row, 0, section['title'], bold)
            row += 1
            sheet.write(row, 0, 'Назва показників', head)
            sheet.write(row, 1, 'Код рядка', head)
            for index, (_column, label) in enumerate(section['columns']):
                sheet.write(row, 2 + index, label, head)
            row += 1
            for form_row in section['rows']:
                sheet.write(row, 0, form_row['name'], wrap)
                sheet.write(row, 1, form_row['code'])
                for index, (column, _label) in enumerate(section['columns']):
                    line = form_row['cells'].get(column)
                    if line:
                        sheet.write_number(row, 2 + index, line.value,
                                           formats[UNIT_DIGITS[line.unit]])
                row += 1
            row += 1
        workbook.close()
        filename = '1-PV_%s_%s.xlsx' % (self.company_id.edrpou or self.company_id.id,
                                        self.period_key)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }


class HrReportLaborLine(models.Model):
    _name = 'hr.report.labor.line'
    _description = 'Labour Report 1-PV Row'
    _order = 'report_id, sequence, id'

    report_id = fields.Many2one('hr.report.labor', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='report_id.company_id', store=True)
    report_state = fields.Selection(related='report_id.state')
    sequence = fields.Integer()
    section = fields.Char(required=True)
    code = fields.Char(string='Row Code', required=True)
    column_no = fields.Char(string='Column', required=True)
    column_label = fields.Char(string='Column Name', compute='_compute_column_label')
    name = fields.Char(string='Indicator', required=True)
    unit = fields.Selection([
        ('kuah', 'Thousand UAH'),
        ('uah', 'UAH'),
        ('persons', 'Persons'),
        ('hours', 'Person-hours'),
        ('units', 'Units'),
    ], required=True)
    is_auto = fields.Boolean(
        string='Computed', readonly=True,
        help='Odoo computes this row. Rows it has no data for are entered by hand.')
    computed_value = fields.Float(string='Computed Value', digits=(16, 2), readonly=True)
    is_manual = fields.Boolean(
        string='Manual',
        help='Report the value entered by hand instead of the computed one. '
             'The value is kept when the report is recomputed.')
    manual_value = fields.Float(string='Manual Value', digits=(16, 2))
    value = fields.Float(string='Value', digits=(16, 2), compute='_compute_value', store=True)

    _report_cell_uniq = models.Constraint(
        'unique(report_id, code, column_no)',
        'A row of the 1-PV report can only appear once!',
    )

    @api.depends('report_id.period_type', 'section', 'column_no')
    def _compute_column_label(self):
        for line in self:
            columns = COLUMNS.get((line.report_id.period_type, line.section), {})
            line.column_label = columns.get(line.column_no, line.column_no)

    @api.depends('is_manual', 'manual_value', 'computed_value', 'unit')
    def _compute_value(self):
        for line in self:
            value = line.manual_value if line.is_manual else line.computed_value
            line.value = float_round(value, precision_digits=UNIT_DIGITS.get(line.unit, 2))

    def _to_form_units(self, value):
        self.ensure_one()
        if self.unit == 'kuah':
            value = value / 1000.0
        return float_round(value or 0.0, precision_digits=UNIT_DIGITS[self.unit],
                           rounding_method='HALF-UP')

    @api.onchange('is_manual')
    def _onchange_is_manual(self):
        if self.is_manual and not self.manual_value:
            self.manual_value = self.computed_value

    def write(self, vals):
        if any(line.report_id.state == 'done' for line in self) \
                and set(vals) & {'is_manual', 'manual_value'}:
            raise UserError(_('Reset the report to draft to change its rows.'))
        return super().write(vals)
