"""Податкова декларація з податку на прибуток підприємств (J0100129) з додатком РІ (J0111829).

Форма — наказ Мінфіну від 20.10.2015 № 897 у редакції наказу від 20.02.2023 № 101
(зі змінами, останні — наказ № 371 від 25.07.2025). Структура — XSD з пакета СКЗ ДПС
1.34.0.0 (``data/xsd``); версія 29 діє за ``spr_ver.xml`` для періодів з 01.10.2025
без кінцевої дати. Нова версія форми (J0100130 — проєкт, наказ № 186) додається рядком
у ``FORM_VERSIONS`` і своїми XSD.

Розрахунок (розділ III ПКУ):

* рядок 01 — дохід за правилами бухобліку: рядки 2000, 2120, 2200, 2220, 2240 Ф2
  (обороти 70–74 без закриття через 79), наростаючим підсумком з 1 січня;
* рядок 02 — фінансовий результат до оподаткування (рядок 2290 / 2295 Ф2, зі знаком);
* рядок 03 РІ — різниці з додатка РІ, які вносить бухгалтер (автоматичних податкових
  різниць немає — #76); платник з доходом до 40 млн грн може відмовитися від
  коригувань (пп. 134.1.1 ПКУ) — тоді лишається тільки рядок 3.2.4 (збитки минулих років);
* рядок 04 = 02 + 03 РІ; рядок 06 = додатне значення рядка 04 × 18 / 100 (п. 136.1);
* рядок 17 = рядок 06; рядок 18 — рядок 17 декларації за попередній період року
  (лише для квартальних платників), рядок 19 = 17 − 18.

Не формуються: уточнююча декларація (рядки 29–47, додаток ВП), рядок 05 ПЗ (пільги),
16 ЗП, 06.1–06.4 (КІК, МПЗ, Дія Сіті, ТЦ), рядки 07–15 (страховики, лотереї, азартні
ігри), 20–28 (авансові внески АВ, ПН, ЩАВ), додатки АМ (амортизація, а з ним і розділ 1
РІ), ЦП, ТЦ, БД; фінансова звітність не прив'язується як додаток (LINKED_DOCS) —
її подають модулем l10n_ua_fin_report_dps.
"""
import base64
import re
from calendar import monthrange
from datetime import date
from xml.sax.saxutils import escape

from lxml import etree

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
from odoo.tools.misc import file_path

from odoo.addons.l10n_ua_accounting.models.l10n_ua_pnl_report import pnl_complete
from odoo.addons.l10n_ua_tax_cabinet.models.l10n_ua_dps_submit_mixin import dps_standard_filename

XS = '{http://www.w3.org/2001/XMLSchema}'
SOFTWARE = 'Odoo l10n_ua'

# Версії форми: (кінець звітного періоду від, до (включно) або None, декларація, РІ).
# Межі — D_BEGIN / D_END з spr_ver.xml СКЗ ДПС.
FORM_VERSIONS = [
    (date(2025, 10, 1), None, 'J0100129', 'J0111829'),
]

# Звітний період → (PERIOD_TYPE, PERIOD_MONTH, позначка періоду в тілі).
PERIODS = {
    'q1': ('2', 3, 'H1KV'),
    'h1': ('3', 6, 'HHY'),
    '9m': ('4', 9, 'H3KV'),
    'year': ('5', 12, 'HY'),
}
PERIOD_ORDER = ['q1', 'h1', '9m', 'year']

# Рядки додатка РІ, які вносить бухгалтер: (поле, код рядка, елемент XSD, знак).
# Знак «+» — різниця збільшує фінансовий результат (рядок 01 РІ), «−» — зменшує (02 РІ).
RI_ROWS = [
    ('ri_2_1_1', '2.1.1', 'R0211G3', 1),
    ('ri_2_2_1', '2.2.1', 'R0221G3', -1),
    ('ri_2_1_2', '2.1.2', 'R0212G3', 1),
    ('ri_2_2_2', '2.2.2', 'R0222G3', -1),
    ('ri_2_1_3', '2.1.3', 'R0213G3', 1),
    ('ri_2_2_3', '2.2.3', 'R0223G3', -1),
    ('ri_3_1_1', '3.1.1', 'R0311G3', 1),
    ('ri_3_2_1', '3.2.1', 'R0321G3', -1),
    ('ri_3_2_3', '3.2.3', 'R0323G3', -1),
    ('ri_3_2_4', '3.2.4', 'R0324G3', -1),
    ('ri_3_1_10', '3.1.10', 'R03110G3', 1),
    ('ri_3_1_11', '3.1.11', 'R03111G3', 1),
]
# Від'ємне значення об'єкта оподаткування минулих років — єдиний рядок РІ, що лишається
# при рішенні не застосовувати коригування (пп. 134.1.1 ПКУ).
RI_LOSS_FIELD = 'ri_3_2_4'

# Дохід за правилами бухобліку (рядок 01): рядки Ф2 2000, 2120, 2200, 2220, 2240.
INCOME_KEYS = ('net_revenue', 'other_operating_income', 'equity_income',
               'financial_income', 'other_income')

LOCKED_STATES = ('submitted', 'accepted')
UNLOCK_CTX = 'l10n_ua_profit_tax_unlock'

_SCHEMAS = {}


def _schema(form):
    """(XMLSchema, [(елемент, тип)] заголовка, [...] тіла) — з кешем.

    Елементи — у порядку схеми, разом з гілками xs:choice (і послідовностями в них):
    у документ потрапляють тільки ті, що мають значення.
    """
    if form not in _SCHEMAS:
        tree = etree.parse(file_path('l10n_ua_profit_tax/data/xsd/%s.xsd' % form))

        def flatten(node, result):
            for child in node:
                if child.tag == XS + 'element':
                    result.append((child.get('name'), child.get('type')))
                elif child.tag in (XS + 'choice', XS + 'sequence'):
                    flatten(child, result)
            return result

        def elements(type_name):
            sequence = tree.find('.//%scomplexType[@name="%s"]/%ssequence' % (XS, type_name, XS))
            return flatten(sequence, [])

        _SCHEMAS[form] = (etree.XMLSchema(tree), elements('DHead'), elements('DBody'))
    return _SCHEMAS[form]


def _uah(value):
    """Ціла гривня (DGdecimal0), округлення за арифметичними правилами."""
    return int(float_round(value or 0.0, precision_digits=0))


class L10nUaProfitTaxDeclaration(models.Model):
    _name = 'l10n_ua.profit.tax.declaration'
    _description = 'Corporate Profit Tax Declaration'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'year desc, period desc, id desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    year = fields.Integer(
        string='Year', required=True, tracking=True,
        default=lambda self: fields.Date.context_today(self).year)
    period = fields.Selection(
        [('q1', 'Q1'), ('h1', 'Half-year'), ('9m', 'Three quarters'), ('year', 'Year')],
        string='Reporting Period', required=True, tracking=True,
        help='The declaration is cumulative from 1 January of the year.')
    base_period = fields.Selection(
        [('quarter', 'Quarter'), ('year', 'Year')],
        string='Base Reporting Period', required=True, default='quarter', tracking=True,
        help='Quarter: the declaration is filed for Q1, half-year, three quarters and '
             'year (art. 137.4 of the Tax Code). Year: annual filing only — payers whose '
             'income for the last annual period does not exceed UAH 40 million, '
             'agricultural producers, new payers (art. 137.5).')
    doc_kind = fields.Selection(
        [('HZ', 'Reporting'), ('HZN', 'New reporting')],
        string='Declaration Type', required=True, default='HZ', tracking=True,
        help='New reporting declaration replaces the one already filed for the same '
             'period before the filing deadline.')
    state = fields.Selection(
        [('draft', 'Draft'), ('calculated', 'Calculated'),
         ('submitted', 'Submitted'), ('accepted', 'Accepted')],
        string='Status', default='draft', tracking=True, copy=False)
    no_adjustments = fields.Boolean(
        string='No Adjustments to the Financial Result',
        help='Decision not to apply the tax differences (sub-paragraph 134.1.1 of the '
             'Tax Code): allowed for payers whose income for the last annual reporting '
             'period does not exceed UAH 40 million. Only the loss of previous years '
             '(row 3.2.4 of appendix РІ) still reduces the result.')
    tax_rate = fields.Float(
        string='Tax Rate, %', default=18.0, required=True,
        help='Basic profit tax rate (paragraph 136.1 of the Tax Code).')

    # --- з бухобліку
    line_01 = fields.Monetary(
        string='01. Income (accounting)', copy=False,
        help='Income from any activity less indirect taxes, by accounting rules: rows '
             '2000, 2120, 2200, 2220 and 2240 of form 2 (turnover of accounts 70–74), '
             'cumulative from 1 January. Filled by «Calculate».')
    line_02 = fields.Monetary(
        string='02. Financial Result Before Tax', copy=False,
        help='Profit (+) or loss (−) before tax per the financial statements: row 2290 '
             'or 2295 of form 2, cumulative from 1 January. Filled by «Calculate».')

    # --- додаток РІ (вносить бухгалтер)
    ri_2_1_1 = fields.Monetary(
        string='2.1.1 Provisions created (+)', copy=False,
        help='Expenses on provisions for future expenses (except vacation pay and related '
             'ESV), sub-paragraph 139.1.1.')
    ri_2_2_1 = fields.Monetary(
        string='2.2.1 Provisions used (−)', copy=False,
        help='Use of provisions created for future expenses, sub-paragraph 139.1.2.')
    ri_2_1_2 = fields.Monetary(
        string='2.1.2 Doubtful debts reserve (+)', copy=False,
        help='Expenses on the doubtful debts reserve / expected credit losses, '
             'sub-paragraph 139.2.1.')
    ri_2_2_2 = fields.Monetary(
        string='2.2.2 Doubtful debts reserve decrease (−)', copy=False,
        help='Decrease of the doubtful debts reserve that increased the financial '
             'result, sub-paragraph 139.2.2.')
    ri_2_1_3 = fields.Monetary(
        string='2.1.3 Receivables written off over the reserve (+)', copy=False,
        help='Receivables written off over the doubtful debts reserve, '
             'sub-paragraph 139.2.1.')
    ri_2_2_3 = fields.Monetary(
        string='2.2.3 Bad debts written off (−)', copy=False,
        help='Receivables written off that meet the bad debt criteria of sub-paragraph '
             '14.1.11, sub-paragraph 139.2.2.')
    ri_3_1_1 = fields.Monetary(
        string='3.1.1 Excess interest (+)', copy=False,
        help='Excess of interest on loans and other debt obligations, paragraph 140.2.')
    ri_3_2_1 = fields.Monetary(
        string='3.2.1 Interest carried forward (−)', copy=False,
        help='Interest of previous periods reduced annually by 5 %, paragraph 140.3.')
    ri_3_2_3 = fields.Monetary(
        string='3.2.3 Income from equity participation (−)', copy=False,
        help='Accrued income from participation in the capital of other profit tax or '
             'single tax payers, sub-paragraph 140.4.1.')
    ri_3_2_4 = fields.Monetary(
        string='3.2.4 Loss of previous years (−)', copy=False,
        help='Negative value of the taxable object of previous tax years, sub-paragraph '
             '140.4.4, with the limits of paragraph 3 of subsection 4 of section XX of '
             'the Tax Code. Enter a positive amount.')
    ri_3_1_10 = fields.Monetary(
        string='3.1.10 Financial aid to non-payers (+)', copy=False,
        help='Non-repayable financial aid (free goods, works, services) given to persons '
             'that are not profit tax payers, sub-paragraph 140.5.10.')
    ri_3_1_11 = fields.Monetary(
        string='3.1.11 Fines and penalties (+)', copy=False,
        help='Fines and penalties charged by tax and other public authorities, '
             'sub-paragraph 140.5.11.')

    ri_increase = fields.Monetary(
        string='01 РІ. Differences increasing the result', compute='_compute_lines', store=True)
    ri_decrease = fields.Monetary(
        string='02 РІ. Differences decreasing the result', compute='_compute_lines', store=True)
    line_03 = fields.Monetary(
        string='03 РІ. Tax Differences', compute='_compute_lines', store=True)
    line_04 = fields.Monetary(
        string='04. Taxable Object', compute='_compute_lines', store=True)
    line_06 = fields.Monetary(
        string='06. Profit Tax', compute='_compute_lines', store=True)
    line_17 = fields.Monetary(
        string='17. Profit Tax for the Period', compute='_compute_lines', store=True)
    line_18 = fields.Monetary(
        string='18. Tax for the Previous Period of the Year', copy=False,
        help='Row 17 of the declaration for the previous reporting period of the year '
             '(quarterly payers). Filled by «Calculate» from the submitted declaration.')
    line_19 = fields.Monetary(
        string='19. Tax Accrued for the Last Quarter', compute='_compute_lines', store=True)

    # --- подання
    signatory_name = fields.Char(
        string='Director', compute='_compute_signatory_name', store=True, readonly=False,
        help='First name and SURNAME of the director (authorized person) who signs.')
    signatory_rnokpp = fields.Char(
        string='Director RNOKPP', compute='_compute_signatory_rnokpp', store=True, readonly=False)
    accountant_name = fields.Char(
        string='Chief Accountant', compute='_compute_accountant_name', store=True, readonly=False)
    accountant_rnokpp = fields.Char(
        string='Chief Accountant RNOKPP', compute='_compute_accountant_rnokpp', store=True,
        readonly=False)
    xml_file = fields.Binary(string='Declaration XML', attachment=True, copy=False)
    xml_filename = fields.Char(string='Declaration File Name', copy=False)
    ri_xml_file = fields.Binary(string='Appendix РІ XML', attachment=True, copy=False)
    ri_xml_filename = fields.Char(string='Appendix РІ File Name', copy=False)
    submission_date = fields.Date(string='Submitted On', copy=False)
    dps_submission_id = fields.Char(string='DPS Submission ID', copy=False, readonly=True)

    # ------------------------------------------------------------------ compute

    @api.depends('year', 'period', 'doc_kind')
    def _compute_name(self):
        labels = dict(self._fields['period'].selection)
        for rec in self:
            name = _('Profit tax declaration %(period)s %(year)s',
                     period=labels.get(rec.period, ''), year=rec.year or '')
            if rec.doc_kind == 'HZN':
                name += _(' (new reporting)')
            rec.name = name

    @staticmethod
    def _company_person(company, field, partner_field):
        """(ім'я, РНОКПП) з кадрового модуля або з реквізитів партнера компанії."""
        employee = company[field] if field in company._fields else False
        if employee:
            rnokpp = employee.rnokpp if 'rnokpp' in employee._fields else False
            return employee.name, rnokpp or False
        partner = company.partner_id
        name = partner[partner_field] if partner_field in partner._fields else False
        return name or False, False

    # Окремий compute на кожне поле: значення, передане в create, захищає всі поля
    # свого compute-методу — спільний метод не підставив би решту.
    @api.depends('company_id')
    def _compute_signatory_name(self):
        for rec in self:
            rec.signatory_name = rec.signatory_name or rec._company_person(
                rec.company_id, 'director_id', 'l10n_ua_chief_name')[0]

    @api.depends('company_id')
    def _compute_signatory_rnokpp(self):
        for rec in self:
            rec.signatory_rnokpp = rec.signatory_rnokpp or rec._company_person(
                rec.company_id, 'director_id', 'l10n_ua_chief_name')[1]

    @api.depends('company_id')
    def _compute_accountant_name(self):
        for rec in self:
            rec.accountant_name = rec.accountant_name or rec._company_person(
                rec.company_id, 'accountant_id', 'l10n_ua_accountant_name')[0]

    @api.depends('company_id')
    def _compute_accountant_rnokpp(self):
        for rec in self:
            rec.accountant_rnokpp = rec.accountant_rnokpp or rec._company_person(
                rec.company_id, 'accountant_id', 'l10n_ua_accountant_name')[1]

    @api.depends('line_01', 'line_02', 'line_18', 'tax_rate', 'base_period', 'period',
                 *[row[0] for row in RI_ROWS])
    def _compute_lines(self):
        for rec in self:
            increase = sum(_uah(rec[f]) for f, _c, _x, sign in RI_ROWS if sign > 0)
            decrease = sum(_uah(rec[f]) for f, _c, _x, sign in RI_ROWS if sign < 0)
            rec.ri_increase = increase
            rec.ri_decrease = decrease
            rec.line_03 = increase - decrease
            rec.line_04 = _uah(rec.line_02) + rec.line_03
            rec.line_06 = _uah(max(rec.line_04, 0.0) * rec.tax_rate / 100)
            rec.line_17 = rec.line_06
            rec.line_19 = rec.line_17 - (_uah(rec.line_18) if rec._has_previous_row() else 0)

    def _has_previous_row(self):
        """Рядок 18 заповнюють квартальні платники за півріччя, три квартали й рік."""
        self.ensure_one()
        return self.base_period == 'quarter' and self.period not in (False, 'q1')

    # ------------------------------------------------------------------ перевірки

    @api.constrains('base_period', 'period')
    def _check_base_period(self):
        for rec in self:
            if rec.base_period == 'year' and rec.period != 'year':
                raise ValidationError(_(
                    'Платник з базовим звітним періодом «рік» подає лише річну декларацію '
                    '(п. 137.5 ПКУ).'))

    @api.constrains('no_adjustments', *[row[0] for row in RI_ROWS])
    def _check_no_adjustments(self):
        for rec in self.filtered('no_adjustments'):
            used = [code for f, code, _x, _s in RI_ROWS
                    if f != RI_LOSS_FIELD and _uah(rec[f])]
            if used:
                raise ValidationError(_(
                    'Прийнято рішення не застосовувати коригування (пп. 134.1.1 ПКУ): '
                    'з різниць лишається тільки рядок 3.2.4 РІ (збитки минулих років). '
                    'Очистіть рядки: %s.') % ', '.join(used))

    @api.constrains('company_id', 'year', 'period', 'doc_kind')
    def _check_unique_reporting(self):
        for rec in self.filtered(lambda d: d.doc_kind == 'HZ'):
            if self.search_count([
                ('company_id', '=', rec.company_id.id), ('year', '=', rec.year),
                ('period', '=', rec.period), ('doc_kind', '=', 'HZ'), ('id', '!=', rec.id),
            ]):
                raise ValidationError(_(
                    'Звітна декларація за цей період уже є. Для заміни поданої до '
                    'граничного строку створіть «звітну нову».'))

    # ------------------------------------------------------------------ розрахунок

    def _period_bounds(self):
        self.ensure_one()
        month = PERIODS[self.period][1]
        return date(self.year, 1, 1), date(self.year, month, monthrange(self.year, month)[1])

    def _form_codes(self):
        """(декларація, РІ) — версія форми, чинна для кінця звітного періоду."""
        self.ensure_one()
        end = self._period_bounds()[1]
        for start, stop, main, ri in FORM_VERSIONS:
            if start <= end and (stop is None or end <= stop):
                return main, ri
        raise UserError(_(
            'Для періоду, що закінчується %s, немає підтримуваної версії форми декларації '
            '(підтримується J0100129 для періодів з IV кварталу 2025 року).')
            % end.strftime('%d.%m.%Y'))

    def _accounting_amounts(self):
        """(рядок 01, рядок 02) — з оборотів рахунків за правилами Ф2, у гривнях."""
        self.ensure_one()
        date_from, date_to = self._period_bounds()
        pnl = self.env['l10n_ua.pnl.report'].new({'company_id': self.company_id.id})
        amounts = pnl_complete(pnl._period_amounts(date_from, date_to))
        income = sum(amounts.get(key, 0.0) for key in INCOME_KEYS)
        return _uah(income), _uah(amounts.get('profit_before_tax', 0.0))

    def _previous_declaration(self):
        """Подана декларація того ж року за попередній період (остання — з урахуванням нових)."""
        self.ensure_one()
        index = PERIOD_ORDER.index(self.period)
        if not index:
            return self.browse()
        return self.search([
            ('company_id', '=', self.company_id.id),
            ('year', '=', self.year),
            ('period', '=', PERIOD_ORDER[index - 1]),
            ('state', 'in', LOCKED_STATES),
            ('id', '!=', self.id),
        ], order='submission_date desc, id desc', limit=1)

    def action_calculate(self):
        for rec in self:
            if rec.state not in ('draft', 'calculated'):
                raise UserError(_('Подану декларацію не перераховують.'))
            rec._form_codes()
            income, result = rec._accounting_amounts()
            vals = {
                'line_01': income,
                'line_02': result,
                'state': 'calculated',
                'xml_file': False, 'xml_filename': False,
                'ri_xml_file': False, 'ri_xml_filename': False,
            }
            if rec._has_previous_row():
                previous = rec._previous_declaration()
                if previous:
                    vals['line_18'] = previous.line_17
            else:
                vals['line_18'] = 0.0
            rec.write(vals)
        return True

    def action_draft(self):
        if self.filtered(lambda d: d.state == 'accepted'):
            raise UserError(_(
                'Декларацію прийнято ДПС — виправити її можна лише уточнюючою декларацією.'))
        for rec in self.filtered(lambda d: d.state == 'submitted'):
            rec.message_post(body=_('Подану декларацію повернуто в чернетку (наприклад, '
                                    'ДПС її не прийняла).'))
        self.with_context(**{UNLOCK_CTX: True}).write({
            'state': 'draft', 'submission_date': False,
            'xml_file': False, 'xml_filename': False,
            'ri_xml_file': False, 'ri_xml_filename': False,
        })

    def action_accept(self):
        self.filtered(lambda d: d.state == 'submitted').with_context(
            **{UNLOCK_CTX: True}).write({'state': 'accepted'})

    def write(self, vals):
        if not self.env.context.get(UNLOCK_CTX) and \
                self.filtered(lambda d: d.state in LOCKED_STATES):
            raise UserError(_(
                'Декларацію подано до ДПС — її не змінюють. Помилку виправляють '
                'уточнюючою декларацією.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_filed(self):
        if self.filtered(lambda d: d.state in LOCKED_STATES):
            raise UserError(_('Подану до ДПС декларацію видалити не можна.'))

    # ------------------------------------------------------------------ XML

    def _office_code(self):
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        return re.sub(r'\D', '', (office.code if office else '') or company.tax_office_code or '')

    def _tin(self):
        company = self.company_id
        return re.sub(r'\D', '', company.edrpou or company.company_registry or '')

    def _kved(self):
        company = self.company_id
        links = company.l10n_ua_kved_ids.sorted(lambda k: (not k.is_primary, k.sequence))
        return (links[:1].code or company.kved_main or '').strip()

    def _has_ri(self):
        self.ensure_one()
        return any(_uah(self[f]) for f, _c, _x, _s in RI_ROWS)

    def _check_xml_ready(self):
        """Усе, чого бракує для XML, — одним повідомленням."""
        self.ensure_one()
        company = self.company_id
        problems = []
        if self.state != 'calculated':
            problems.append(_('спершу розрахуйте декларацію'))
        if not re.fullmatch(r'\d{8}', self._tin()):
            problems.append(_('код ЄДРПОУ компанії (8 цифр)'))
        if not re.fullmatch(r'\d{4}', self._office_code()):
            problems.append(_('податкова інспекція компанії (4-значний код ДПІ)'))
        if not company.l10n_ua_tax_office_id:
            problems.append(_('податковий орган компанії (назва ДПС у декларації)'))
        if not re.fullmatch(r'\d{2}\.\d{1,2}(\.\d)?', self._kved()):
            problems.append(_('основний КВЕД компанії у форматі 00.00'))
        if not (company.city or company.street):
            problems.append(_('адреса компанії'))
        if not self.signatory_name or not re.fullmatch(r'\d{10}', self.signatory_rnokpp or ''):
            problems.append(_('керівник і його РНОКПП (вкладка «Подання»)'))
        if self.accountant_rnokpp and not re.fullmatch(r'\d{10}', self.accountant_rnokpp):
            problems.append(_('РНОКПП головного бухгалтера (10 цифр)'))
        if problems:
            raise UserError(_('Неможливо сформувати XML декларації з податку на прибуток:\n• %s')
                            % '\n• '.join(problems))

    def _doc_state(self):
        """(C_DOC_STAN, C_DOC_TYPE): 1/0 — звітна; 2/№ — звітна нова (наказ № 729)."""
        self.ensure_one()
        if self.doc_kind != 'HZN':
            return '1', 0
        filed = self.search_count([
            ('company_id', '=', self.company_id.id), ('year', '=', self.year),
            ('period', '=', self.period), ('doc_kind', '=', 'HZN'),
            ('state', 'in', LOCKED_STATES), ('id', '!=', self.id),
        ])
        return '2', filed + 1

    def _head_values(self, form):
        self.ensure_one()
        office = self._office_code()
        period_type, period_month, _marker = PERIODS[self.period]
        stan, doc_type = self._doc_state()
        return {
            'TIN': self._tin(), 'C_DOC': form[:3], 'C_DOC_SUB': form[3:6],
            'C_DOC_VER': str(int(form[6:8])), 'C_DOC_TYPE': str(doc_type), 'C_DOC_CNT': '1',
            'C_REG': str(int(office[:2])), 'C_RAJ': str(int(office[2:4])),
            'PERIOD_MONTH': str(period_month), 'PERIOD_TYPE': period_type,
            'PERIOD_YEAR': str(self.year), 'C_STI_ORIG': office, 'C_DOC_STAN': stan,
            'D_FILL': fields.Date.context_today(self).strftime('%d%m%Y'), 'SOFTWARE': SOFTWARE,
        }

    @staticmethod
    def _filename(head):
        """Ім'я файлу за наказом № 729 — з тих самих реквізитів, що й DECLARHEAD."""
        return '%s%s%s%s%s%s%s%s%s%s%s%s%s.xml' % (
            head['C_REG'].zfill(2), head['C_RAJ'].zfill(2), head['TIN'].zfill(10),
            head['C_DOC'], head['C_DOC_SUB'], head['C_DOC_VER'].zfill(2),
            head['C_DOC_STAN'], head['C_DOC_TYPE'].zfill(2), head['C_DOC_CNT'].zfill(7),
            head['PERIOD_TYPE'], head['PERIOD_MONTH'].zfill(2), head['PERIOD_YEAR'],
            head['C_STI_ORIG'].zfill(4))

    @staticmethod
    def _element(name, value):
        return '<%s>%s</%s>' % (name, escape(str(value), {'"': '&quot;', "'": '&apos;'}), name)

    def _render(self, form, head, linked, body_values):
        """XML форми за схемою: елементи в порядку XSD, перевірка схемою — UserError."""
        schema, head_elements, body_elements = _schema(form)
        parts = []
        for name, _type in head_elements:
            if name == 'LINKED_DOCS':
                if linked:
                    parts.append('<LINKED_DOCS>%s</LINKED_DOCS>' % ''.join(
                        '<DOC NUM="%d" TYPE="%s"><C_DOC>%s</C_DOC><C_DOC_SUB>%s</C_DOC_SUB>'
                        '<C_DOC_VER>%s</C_DOC_VER><C_DOC_TYPE>%s</C_DOC_TYPE>'
                        '<C_DOC_CNT>%s</C_DOC_CNT><C_DOC_STAN>%s</C_DOC_STAN>'
                        '<FILENAME>%s</FILENAME></DOC>' % (
                            num, link_type, other['C_DOC'], other['C_DOC_SUB'],
                            other['C_DOC_VER'], other['C_DOC_TYPE'], other['C_DOC_CNT'],
                            other['C_DOC_STAN'], self._filename(other)[:-4] + '.XML')
                        for num, (other, link_type) in enumerate(linked, 1)))
                else:
                    parts.append('<LINKED_DOCS xsi:nil="true"/>')
            elif name in head:
                parts.append(self._element(name, head[name]))
        body = []
        for name, type_ in body_elements:
            value = body_values.get(name)
            if value is None or value is False or value == '':
                continue
            if type_ == 'DGdecimal0':
                value = '%d' % value
            elif type_ == 'DGpercentAlloc':
                value = '%.2f' % value
            body.append(self._element(name, value))
        xml = ('<?xml version="1.0" encoding="windows-1251"?>'
               '<DECLAR xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               'xsi:noNamespaceSchemaLocation="%s.xsd"><DECLARHEAD>%s</DECLARHEAD>'
               '<DECLARBODY>%s</DECLARBODY></DECLAR>') % (form, ''.join(parts), ''.join(body))
        content = xml.encode('windows-1251', errors='xmlcharrefreplace')
        if not schema.validate(etree.fromstring(content)):
            errors = '\n'.join('• %s' % e.message for e in list(schema.error_log)[:5])
            raise UserError(_('XML %(form)s не відповідає схемі ДПС:\n%(errors)s',
                              form=form, errors=errors))
        return content

    def _common_body(self):
        """Шапка тіла, спільна для декларації й додатка: тип, період, ЄДРПОУ."""
        self.ensure_one()
        return {
            self.doc_kind: 1,
            'HZY': str(self.year),
            PERIODS[self.period][2]: 1,
            'HTIN': self._tin(),
            'HBOS': self.signatory_name,
            'HBUH': self.accountant_name or False,
        }

    def _main_body(self, with_ri):
        self.ensure_one()
        company = self.company_id
        office = company.l10n_ua_tax_office_id
        if 'uk_UA' in dict(self.env['res.lang'].get_installed()):
            office = office.with_context(lang='uk_UA')
        address = ', '.join(filter(None, [company.zip, company.state_id.name, company.city,
                                          company.street, company.street2]))
        phone = re.sub(r'[^0-9 ()\-+.,;]', '', company.phone or '')
        values = self._common_body()
        values.update({
            'H01' if self.base_period == 'quarter' else 'H02': 1,
            'HNAME': company._l10n_ua_dps_name(),
            'HKVED': self._kved(),
            'HLOC': address,
            'HZIP': company.zip if re.fullmatch(r'\d{5}', company.zip or '') else False,
            'HTEL': phone if len(phone) >= 4 else False,
            'HEMAIL': company.email if re.fullmatch(r'[^@\s]+@[^@\s]+', company.email or '')
            else False,
            'HSTI': office.name,
            'R001G3': _uah(self.line_01),
            'R002G3': _uah(self.line_02),
            'R004G3': _uah(self.line_04),
            'R006G1': self.tax_rate,
            'R006G3': _uah(self.line_06),
            'R017G3': _uah(self.line_17),
            'R019G3': _uah(self.line_19),
            'HKBOS': self.signatory_rnokpp,
            'HKBUH': self.accountant_rnokpp if self.accountant_name else False,
            'HFILL': fields.Date.context_today(self).strftime('%d%m%Y'),
        })
        if with_ri:
            values.update({'R003G3': _uah(self.line_03), 'HD6': 1})
        if self._has_previous_row() and _uah(self.line_18):
            values['R018G3'] = _uah(self.line_18)
        if self.no_adjustments:
            values['HJ2'] = 1
        return values

    def _ri_body(self):
        self.ensure_one()
        values = self._common_body()
        for field, _code, element, _sign in RI_ROWS:
            if _uah(self[field]):
                values[element] = _uah(self[field])
        values.update({
            'R001G3': _uah(self.ri_increase),
            'R002G3': _uah(self.ri_decrease),
            'R003G3': _uah(self.line_03),
        })
        return values

    def action_generate_xml(self):
        for rec in self:
            rec._check_xml_ready()
            main_form, ri_form = rec._form_codes()
            main_head = rec._head_values(main_form)
            vals = {'ri_xml_file': False, 'ri_xml_filename': False}
            with_ri = rec._has_ri()
            if with_ri:
                ri_head = rec._head_values(ri_form)
                ri_xml = rec._render(ri_form, ri_head, [(main_head, 2)], rec._ri_body())
                vals.update(ri_xml_file=base64.b64encode(ri_xml),
                            ri_xml_filename=dps_standard_filename(ri_xml))
            main_xml = rec._render(main_form, main_head,
                                   [(ri_head, 1)] if with_ri else [],
                                   rec._main_body(with_ri))
            vals.update(xml_file=base64.b64encode(main_xml),
                        xml_filename=dps_standard_filename(main_xml))
            rec.write(vals)
        return True

    # ------------------------------------------------- контракт dps.submit.mixin

    def action_submit(self):
        """Підписати КЕП у браузері й подати декларацію (з додатком РІ) до ДПС."""
        return self.action_kep_submit()

    def _dps_check_can_submit(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Подати можна тільки розраховану декларацію.'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати декларацію з податку на прибуток до ДПС')

    def kep_prepare_signing(self):
        spec = super().kep_prepare_signing()
        if self.ri_xml_file:
            doc = dict(spec['documents'][0])
            data = self.ri_xml_file
            doc.update(name='ri', data_b64=data.decode() if isinstance(data, bytes) else data,
                       filename=self.ri_xml_filename)
            spec['documents'].append(doc)
        return spec

    def kep_submit_signed(self, signed, auth_signature=None):
        """Декларація з додатком — одним запитом: кабінет приймає масив звітів."""
        self.ensure_one()
        if not self.ri_xml_file:
            return super().kep_submit_signed(signed, auth_signature)
        self._dps_check_can_submit()
        config = self._dps_config()
        if not signed.get('doc') or not signed.get('ri'):
            raise UserError(_('Не отримано підпис декларації або додатка РІ.'))
        result = config._api_submit_document_presigned(
            signed['doc'], self._dps_filename(), auth_signature,
            extra_files=[(signed['ri'], self.ri_xml_filename)])
        self._dps_check_result(result)
        receipt = self._dps_receipt_text(result)
        self._dps_store_receipts(result)
        self._dps_on_submitted(receipt)
        return {'receipt': receipt}

    def _dps_store_receipts(self, result):
        for item in result if isinstance(result, list) else [result]:
            if isinstance(item, dict) and item.get('id'):
                self.with_context(**{UNLOCK_CTX: True}).dps_submission_id = str(item['id'])
                break
        return super()._dps_store_receipts(result)

    def _dps_on_submitted(self, receipt):
        self.with_context(**{UNLOCK_CTX: True}).write({
            'state': 'submitted',
            'submission_date': fields.Date.context_today(self),
        })
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))
