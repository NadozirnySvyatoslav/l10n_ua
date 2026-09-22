import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


PERIOD_QUARTERS = {
    'q1': ['1'],
    'h1': ['1', '2'],
    '9m': ['1', '2', '3'],
    'year': ['1', '2', '3', '4'],
}

# Reporting period → (PERIOD_TYPE code, PERIOD_MONTH, quarter marker tag) for F0103309.
# The single-tax declaration is cumulative, so the marker follows the last covered quarter.
PERIOD_F0103309 = {
    'q1': ('2', '3', 'H1KV'),
    'h1': ('3', '6', 'H2KV'),
    '9m': ('4', '9', 'H3KV'),
    'year': ('5', '12', 'H4KV'),
}

# Групи з фіксованими ЄП і військовим збором (1, 2); F0103309 — декларація 3 групи.
FIXED_TAX_GROUPS = ('1', '2')
# Військовий збір платників ЄП діє з 01.01.2025:
# 3 група — % доходу; 1–2 групи — % мінімальної зарплати щомісяця.
FOP_MILITARY_FROM_YEAR = 2025
FOP_MILITARY_RATE = 1.0
FOP_MILITARY_MIN_WAGE_SHARE = 10.0

PERIOD_MONTHS = {
    'q1': 3,
    'h1': 6,
    '9m': 9,
    'year': 12,
}


class L10nUaFopDeclaration(models.Model):
    _name = 'l10n_ua.fop.declaration'
    _description = 'Декларація платника єдиного податку'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'l10n_ua.dps.submit.mixin']
    _order = 'year desc, period desc'

    name = fields.Char(
        string='Назва',
        compute='_compute_name',
        store=True,
    )
    year = fields.Integer(
        string='Рік',
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        tracking=True,
    )
    period = fields.Selection(
        selection=[
            ('q1', 'I квартал'),
            ('h1', 'Півріччя'),
            ('9m', '9 місяців'),
            ('year', 'Рік'),
        ],
        string='Звітний період',
        required=True,
        tracking=True,
    )
    fop_group_id = fields.Many2one(
        'l10n_ua.fop.group',
        string='Група ЄП',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )

    # Income from books
    income_book_ids = fields.Many2many(
        'l10n_ua.fop.income.book',
        string='Книги обліку доходів',
        compute='_compute_income_books',
    )
    total_income = fields.Monetary(
        string='Загальний дохід',
        currency_field='currency_id',
        tracking=True,
    )
    income_limit = fields.Monetary(
        string='Ліміт доходу',
        compute='_compute_income_limit',
        store=True,
        currency_field='currency_id',
        help='Граничний дохід групи: множник групи × мінімальна заробітна плата '
             'на 1 січня року декларації (п. 291.4 ПКУ).',
    )
    income_limit_exceeded = fields.Boolean(
        string='Ліміт перевищено',
        compute='_compute_income_limit_exceeded',
        store=True,
    )

    # Single tax
    tax_rate = fields.Float(
        string='Ставка ЄП (%)',
        related='fop_group_id.tax_rate',
    )
    monthly_tax_amount = fields.Monetary(
        string='Місячна сума ЄП',
        currency_field='currency_id',
        help='Для груп 1 та 2 — фіксована місячна сума єдиного податку',
    )
    single_tax = fields.Monetary(
        string='Єдиний податок',
        compute='_compute_taxes',
        store=True,
        currency_field='currency_id',
    )

    # ESV
    min_wage = fields.Monetary(
        string='Мінімальна зарплата',
        compute='_compute_min_wage',
        store=True,
        currency_field='currency_id',
        help='Мінімальна заробітна плата на кінець звітного періоду (довідник '
             '«Мінімальна заробітна плата»). ЄСВ рахується від мінімальної '
             'зарплати кожного місяця періоду.',
    )
    esv_rate = fields.Float(
        string='Ставка ЄСВ (%)',
        default=22.0,
    )
    esv_months = fields.Integer(
        string='Кількість місяців',
        compute='_compute_esv_months',
    )
    esv_base = fields.Monetary(
        string='База нарахування ЄСВ',
        compute='_compute_taxes',
        store=True,
        currency_field='currency_id',
    )
    esv_amount = fields.Monetary(
        string='Сума ЄСВ',
        compute='_compute_taxes',
        store=True,
        currency_field='currency_id',
    )

    # Military levy
    military_levy = fields.Monetary(
        string='Військовий збір',
        compute='_compute_taxes',
        store=True,
        currency_field='currency_id',
        help='З 2025 року: 1–2 групи — 10 % мінімальної заробітної плати за кожен '
             'місяць періоду; 3 група — 1 % доходу.',
    )

    # Totals
    total_payable = fields.Monetary(
        string='Всього до сплати',
        compute='_compute_taxes',
        store=True,
        currency_field='currency_id',
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('calculated', 'Розраховано'),
            ('submitted', 'Подано'),
            ('accepted', 'Прийнято'),
        ],
        string='Статус',
        default='draft',
        tracking=True,
    )
    submission_date = fields.Date(
        string='Дата подання',
    )
    notes = fields.Html(
        string='Примітки',
    )
    xml_file = fields.Binary(
        string='XML файл',
    )
    xml_filename = fields.Char(
        string='Ім\'я файлу',
    )

    _unique_declaration = models.Constraint(
        'unique(year, period, fop_group_id, company_id)',
        'Декларація за цей період та групу вже існує!',
    )

    @api.depends('year', 'period', 'fop_group_id')
    def _compute_name(self):
        period_names = {
            'q1': 'I кв.',
            'h1': 'Півріччя',
            '9m': '9 міс.',
            'year': 'Рік',
        }
        for rec in self:
            period_name = period_names.get(rec.period, '')
            group_name = rec.fop_group_id.name if rec.fop_group_id else ''
            rec.name = f'Декларація ЄП {period_name} {rec.year} ({group_name})'

    @api.depends('year', 'period', 'fop_group_id', 'company_id')
    def _compute_income_books(self):
        for rec in self:
            if rec.year and rec.period and rec.fop_group_id:
                quarters = PERIOD_QUARTERS.get(rec.period, [])
                books = self.env['l10n_ua.fop.income.book'].search([
                    ('year', '=', rec.year),
                    ('quarter', 'in', quarters),
                    ('fop_group_id', '=', rec.fop_group_id.id),
                    ('company_id', '=', rec.company_id.id),
                ])
                rec.income_book_ids = books
            else:
                rec.income_book_ids = False

    def _period_month_min_wages(self):
        """Мінімальна зарплата кожного місяця звітного періоду (від січня).

        Нуль на місці місяця означає, що на цей рік довідник ще не заповнено.
        """
        self.ensure_one()
        if not self.year or not self.period:
            return []
        MinWage = self.env['l10n_ua.min.wage']
        return [
            MinWage._get_amount(f'{self.year}-{month:02d}-01')
            for month in range(1, PERIOD_MONTHS.get(self.period, 0) + 1)
        ]

    @api.depends('year', 'fop_group_id.limit_min_wages')
    def _compute_income_limit(self):
        for rec in self:
            rec.income_limit = (
                rec.fop_group_id._get_income_limit(rec.year)
                if rec.fop_group_id and rec.year else 0.0
            )

    @api.depends('total_income', 'income_limit')
    def _compute_income_limit_exceeded(self):
        for rec in self:
            rec.income_limit_exceeded = (
                rec.income_limit > 0 and rec.total_income > rec.income_limit
            )

    @api.depends('year', 'period')
    def _compute_min_wage(self):
        for rec in self:
            month_wages = rec._period_month_min_wages()
            rec.min_wage = month_wages[-1] if month_wages else 0.0

    @api.depends('period')
    def _compute_esv_months(self):
        for rec in self:
            rec.esv_months = PERIOD_MONTHS.get(rec.period, 0)

    @api.depends(
        'total_income', 'tax_rate', 'monthly_tax_amount',
        'year', 'esv_rate', 'period', 'fop_group_id',
    )
    def _compute_taxes(self):
        for rec in self:
            months = PERIOD_MONTHS.get(rec.period, 0)
            group_code = rec.fop_group_id.code if rec.fop_group_id else ''
            month_wages = rec._period_month_min_wages()

            # Single tax: groups 1,2 — fixed monthly; group 3 — % of income
            if group_code in FIXED_TAX_GROUPS:
                rec.single_tax = rec.monthly_tax_amount * months
            else:
                rec.single_tax = (
                    rec.total_income * (rec.tax_rate / 100)
                    if rec.tax_rate else 0
                )

            # ESV: мінімальний внесок щомісяця — від мінзарплати цього місяця
            # (у 2024 вона змінилась з квітня, тож «одна сума × місяці» хибна).
            rec.esv_base = sum(month_wages)
            rec.esv_amount = (
                rec.esv_base * (rec.esv_rate / 100) if rec.esv_base else 0
            )

            if not rec.year or rec.year < FOP_MILITARY_FROM_YEAR:
                rec.military_levy = 0.0
            elif group_code in FIXED_TAX_GROUPS:
                rec.military_levy = round(
                    sum(month_wages) * FOP_MILITARY_MIN_WAGE_SHARE / 100, 2)
            else:
                rec.military_levy = round(
                    rec.total_income * FOP_MILITARY_RATE / 100, 2)

            rec.total_payable = rec.single_tax + rec.esv_amount + rec.military_levy

    def action_calculate(self):
        """Розрахувати декларацію на основі книг обліку доходів."""
        for rec in self:
            if not rec.period or not rec.fop_group_id:
                raise UserError(
                    'Вкажіть звітний період та групу ЄП перед розрахунком.'
                )

            # Довідник мінзарплати міг змінитися вже після створення декларації
            # (додали новий рік) — збережені суми треба перерахувати.
            for fname in ('min_wage', 'income_limit', 'income_limit_exceeded',
                          'esv_base', 'esv_amount', 'military_levy', 'total_payable'):
                self.env.add_to_compute(rec._fields[fname], rec)

            if not all(rec._period_month_min_wages()):
                raise UserError(_(
                    'У довіднику немає мінімальної заробітної плати на %s рік — '
                    'від неї рахуються ЄСВ і ліміт доходу групи. Додайте розмір: '
                    'Taxes UA → Configuration → Мінімальна заробітна плата.'
                ) % rec.year)

            # Find matching income books
            quarters = PERIOD_QUARTERS.get(rec.period, [])
            books = self.env['l10n_ua.fop.income.book'].search([
                ('year', '=', rec.year),
                ('quarter', 'in', quarters),
                ('fop_group_id', '=', rec.fop_group_id.id),
                ('company_id', '=', rec.company_id.id),
                ('state', '=', 'confirmed'),
            ])

            if not books:
                raise UserError(
                    f'Не знайдено підтверджених книг обліку доходів '
                    f'за {rec.year} рік, квартали: '
                    f'{", ".join(quarters)}.\n'
                    f'Створіть та підтвердіть книги обліку перед розрахунком.'
                )

            total_income = sum(books.mapped('total_income'))

            rec.write({
                'total_income': total_income,
                'state': 'calculated',
            })

            # Check income limit
            if rec.income_limit_exceeded:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Увага!',
                        'message': (
                            f'Дохід {rec.total_income:,.2f} грн перевищує '
                            f'ліміт {rec.income_limit:,.2f} грн для '
                            f'{rec.fop_group_id.name}!'
                        ),
                        'type': 'warning',
                        'sticky': True,
                    },
                }

    def action_submit(self):
        """Відкрити КЕП-підпис і подання декларації ЄП до ДПС."""
        return self.action_kep_submit()

    def _check_f0103309_group(self):
        """F0103309 — декларація 3 групи; для 1–2 груп подається інша, річна форма."""
        for rec in self:
            if rec.fop_group_id.code in FIXED_TAX_GROUPS:
                raise UserError(_(
                    'Форма F0103309 — декларація платника єдиного податку 3 групи. '
                    'ФОП %s групи подають окрему річну декларацію, формування якої '
                    'ще не підтримується: подайте її в Електронному кабінеті ДПС.'
                ) % rec.fop_group_id.code)

    # --- контракт l10n_ua.dps.submit.mixin ---

    def _dps_check_can_submit(self):
        self._check_f0103309_group()
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_(
                    'Спершу розрахуйте декларацію (кнопка «Розрахувати»).'))

    def _dps_ensure_xml(self):
        self.ensure_one()
        if not self.xml_file:
            self.action_generate_xml()

    def _dps_submit_label(self):
        return _('Подати декларацію ЄП до ДПС')

    def _dps_on_submitted(self, receipt):
        self.write({
            'state': 'submitted',
            'submission_date': fields.Date.context_today(self),
        })
        self.message_post(body=_('Подано до ДПС. Квитанція: %s') % (receipt or '—'))

    def action_accept(self):
        self.write({'state': 'accepted'})

    def action_draft(self):
        self.write({
            'state': 'draft',
            'submission_date': False,
        })

    def action_view_income_books(self):
        """Відкрити пов'язані книги обліку доходів."""
        self.ensure_one()
        books = self.income_book_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Книги обліку доходів',
            'res_model': 'l10n_ua.fop.income.book',
            'view_mode': 'list,form',
            'domain': [('id', 'in', books.ids)],
        }
        if len(books) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = books.id
        return action

    def action_generate_xml(self):
        """Згенерувати XML декларації ЄП (форма F0103309) для подання до ДПС.

        Делегує рендеринг до єдиного канонічного генератора з
        l10n_ua_tax_F0103309, щоб не дублювати шаблон декларації.
        """
        self.ensure_one()
        self._check_f0103309_group()
        if self.state == 'draft':
            raise UserError(
                'Спершу розрахуйте декларацію (кнопка «Розрахувати»), '
                'потім формуйте XML.'
            )

        period_type, period_month, quarter_marker = PERIOD_F0103309.get(
            self.period, ('5', '12', 'H4KV'))

        company = self.company_id
        tax_office = company.l10n_ua_tax_office_id
        activities = [
            (link.kved_id.code, link.kved_id.name)
            for link in company.l10n_ua_kved_ids
        ]

        vals = {
            'taxpayer_tin': company.vat or company.edrpou or '',
            'taxpayer_name': company.name or '',
            'taxpayer_address': self.env['l10n_ua.tax.document.wizard']
                ._format_company_address(company),
            'taxpayer_email': company.email or '',
            'taxpayer_phone': company.phone or '',
            'declaration_type': '0',  # Звітна
            'tax_office_code': tax_office.code if tax_office else '',
            'tax_office_name': tax_office.name if tax_office else '',
            'quarter_marker': quarter_marker,
            'period_type': period_type,
            'period_month': period_month,
            'year': self.year,
            'employee_count': 0,
            'activities': activities,
            'income_total': self.total_income,
            'tax_amount': self.single_tax,
            'tax_paid_prev': 0.0,
            'tax_to_pay': self.single_tax,
            # Декларація не веде авансів, тож увесь військовий збір — до сплати.
            'military_amount': self.military_levy,
            'military_paid_prev': 0.0,
            'military_to_pay': self.military_levy,
        }

        xml = self.env['l10n_ua.tax.document.wizard']._render_F0103309_xml(vals)
        self.xml_filename = (
            f"{vals['taxpayer_tin']}_{self.year}_{period_month}_F0103309.xml"
        )
        self.xml_file = base64.b64encode(xml.encode('windows-1251')).decode()
        return True
