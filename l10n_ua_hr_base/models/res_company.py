import logging
from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta
from pytz import timezone, utc

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Граничні частки заброньованих за Порядком бронювання (ПКМУ № 76 у редакції
# ПКМУ № 1328 від 23.10.2026): 95 % — ОПК і ПЕК за рішенням Міноборони /
# Міненерго, 50 % — базова межа для інших критично важливих підприємств.
RESERVATION_LIMIT_DEFAULTS = {'mod': 95.0, 'minenergo': 95.0, 'other': 50.0}
# Робочі дні на дії роботодавця в «Дії» (п. 9-1, 9-2 Порядку).
EXCEEDED_WORKING_DAYS = 10
LIMIT_ENDED_WORKING_DAYS = 5
# За скільки днів нагадати про завершення строку критичності.
CRITICAL_WARN_DAYS = 30


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Реєстраційні реквізити (ЄДРПОУ, КОАТУУ, КАТОТТГ, код ДПІ, код ПФУ,
    # КВЕД, форма власності, юридична адреса) переїхали в
    # `l10n_ua_company_base`: вони потрібні податковому й бухгалтерському
    # блокам, які кадровий модуль не тягнуть і тягнути не мають (#292).
    # Тут лишається те, що справді кадрове.

    director_id = fields.Many2one(
        'hr.employee', string='Director',
        help='Company director for document signing')
    accountant_id = fields.Many2one(
        'hr.employee', string='Chief Accountant',
        help='Chief accountant for document signing')
    hr_manager_id = fields.Many2one(
        'hr.employee', string='HR Manager',
        help='HR department head for document signing')
    military_officer_id = fields.Many2one(
        'hr.employee', string='Відповідальний за військовий облік',
        help='Особа, відповідальна за ведення військового обліку. Підписує '
             'Списки персонального військового обліку та відомість '
             'оперативного обліку (п. 40 Порядку № 1487), і саме її кадровий '
             'модуль підставляє у друковані форми за замовчуванням.')

    # Staffing table settings
    wage_from_staffing = fields.Selection([
        ('none', 'Do not use'),
        ('suggest', 'Suggest (fill on selection)'),
        ('fallback', 'Fallback (use if wage is 0)'),
        ('both', 'Both (suggest + fallback)'),
    ], string='Wage from Staffing Table',
       default='both',
       help='How to use salary from staffing table:\n'
            '- Do not use: ignore staffing table salary\n'
            '- Suggest: auto-fill wage when selecting staffing position\n'
            '- Fallback: use staffing salary in payslip if contract wage is 0\n'
            '- Both: suggest on selection + fallback in payslip')

    # === Критично важливе підприємство і ліміт бронювання (#524) ===
    # Порядок бронювання (ПКМУ № 76 від 27.01.2023 у редакції ПКМУ № 1328 від
    # 23.10.2026) обмежує частку заброньованих військовозобов'язаних, а
    # роботодавця зобов'язує стежити за нею сам: перевищення — 10 робочих днів
    # на заяву про анулювання, кінець збільшеного ліміту — 5 робочих днів.
    l10n_ua_critical_enterprise = fields.Boolean(
        string='Критично важливе підприємство',
        help='Підприємство має рішення про визначення критично важливим для '
             'бронювання військовозобов\'язаних (Порядок № 76, ПКМУ № 1608, '
             'ПКМУ № 1328).')
    l10n_ua_critical_authority = fields.Selection([
        ('mod', 'Міноборони (ОПК)'),
        ('minenergo', 'Міненерго (ПЕК)'),
        ('other', 'Інший орган / обласна військова адміністрація'),
    ], string='Орган, що визначив критичність', default='other',
        help='Від органу залежить гранична частка: ОПК і ПЕК — до 95 % '
             'військовозобов\'язаних, зазначених у рішенні міністерства; інші — '
             'базово до 50 %.')
    l10n_ua_critical_decision = fields.Char(
        string='Рішення про критичність',
        help='Номер і дата рішення органу.')
    l10n_ua_critical_until = fields.Date(
        string='Критичність діє до',
        help='Строк, зазначений у рішенні. За 30 днів до нього кадровик '
             'отримає нагадування.')
    l10n_ua_reservation_limit = fields.Float(
        string='Граничний відсоток бронювання', default=50.0, digits=(5, 2),
        help='Максимальна частка заброньованих серед військовозобов\'язаних. '
             'Понад базову межу — лише за рішенням органу.')
    l10n_ua_reservation_limit_until = fields.Date(
        string='Збільшений ліміт діє до',
        help='Строк рішення про збільшений ліміт (не більше одного року; для '
             'рішень Міноборони до 09.12.2025 — не довше 08.12.2026). Після '
             'нього роботодавець має 5 робочих днів, щоб анулювати зайві '
             'відстрочки.')
    l10n_ua_reservation_base = fields.Integer(
        string='Військовозобов\'язаних у рішенні',
        help='Для ОПК і ПЕК частка рахується від кількості, зазначеної в '
             'рішенні Міноборони чи Міненерго. Порожньо — рахувати з карток '
             'працівників.')
    l10n_ua_liable_count = fields.Integer(
        string='Військовозобов\'язаних (з карток)',
        compute='_compute_l10n_ua_reservation_share')
    l10n_ua_reserved_count = fields.Integer(
        string='Заброньовано', compute='_compute_l10n_ua_reservation_share')
    l10n_ua_reservation_share = fields.Float(
        string='Частка заброньованих, %', digits=(5, 2),
        compute='_compute_l10n_ua_reservation_share')
    l10n_ua_reservation_exceeded = fields.Boolean(
        string='Ліміт перевищено', compute='_compute_l10n_ua_reservation_share')
    # Дати, про які вже нагадали: нагадування про строк — одне на строк.
    l10n_ua_limit_end_notified = fields.Date(copy=False)
    l10n_ua_critical_end_notified = fields.Date(copy=False)

    _l10n_ua_reservation_limit_range = models.Constraint(
        'CHECK(l10n_ua_reservation_limit >= 0 AND l10n_ua_reservation_limit <= 100)',
        'Граничний відсоток бронювання має бути від 0 до 100.',
    )

    @api.onchange('l10n_ua_critical_authority')
    def _onchange_l10n_ua_critical_authority(self):
        for company in self:
            if company.l10n_ua_critical_authority:
                company.l10n_ua_reservation_limit = RESERVATION_LIMIT_DEFAULTS[
                    company.l10n_ua_critical_authority]

    def _l10n_ua_liable_employees(self):
        """Працюючі військовозобов'язані компанії — база для частки.

        Працівники з відстрочкою з інших підстав теж тут: за ПКМУ № 1328 вони
        знову враховуються в базу. Призовників і резервістів Порядок
        бронювання не охоплює.
        """
        self.ensure_one()
        # sudo: частку бачить і той, хто відкриває компанію без прав на HR.
        return self.env['hr.employee'].sudo().search([
            ('company_id', '=', self._origin.id),
            ('military_register_category', '=', 'liable'),
        ]).filtered('military_accounting_applicable')

    @api.depends('l10n_ua_reservation_limit', 'l10n_ua_reservation_base',
                 'l10n_ua_critical_enterprise')
    def _compute_l10n_ua_reservation_share(self):
        for company in self:
            liable = company._l10n_ua_liable_employees() if company._origin.id \
                else self.env['hr.employee']
            reserved = liable.filtered(
                lambda e: e.military_reservation and not e.military_reservation_expired)
            base = company.l10n_ua_reservation_base or len(liable)
            share = 100.0 * len(reserved) / base if base else 0.0
            company.l10n_ua_liable_count = len(liable)
            company.l10n_ua_reserved_count = len(reserved)
            company.l10n_ua_reservation_share = share
            company.l10n_ua_reservation_exceeded = bool(
                company.l10n_ua_critical_enterprise and reserved
                and share > company.l10n_ua_reservation_limit + 1e-9)

    def _l10n_ua_add_working_days(self, start, days):
        """Дата, що настає через `days` робочих днів після `start`."""
        self.ensure_one()
        span = self._l10n_ua_working_dates(
            start + relativedelta(days=1), start + relativedelta(days=days * 2 + 14))
        holidays = self._l10n_ua_public_holiday_dates(
            start + relativedelta(days=1), start + relativedelta(days=days * 2 + 14))
        working = sorted(d for d in span if d not in holidays)
        return working[days - 1] if len(working) >= days else start + relativedelta(days=days)

    def _l10n_ua_reservation_responsible(self):
        """(картка працівника, користувач) для нагадувань про бронювання."""
        self.ensure_one()
        employee = (self.military_officer_id or self.hr_manager_id
                    or self.director_id)
        user = employee.user_id
        if not user:
            group = self.env.ref('l10n_ua_hr_base.group_hr_ua_officer',
                                 raise_if_not_found=False)
            user = group.user_ids.filtered(
                lambda u: self in u.company_ids)[:1] if group else user
        return employee, user

    def _l10n_ua_reservation_remind(self, summary, note, deadline):
        """Задача відповідальному в картці; одна відкрита на одну подію."""
        self.ensure_one()
        employee, user = self._l10n_ua_reservation_responsible()
        if not employee or not user:
            _logger.warning('Бронювання (%s): %s — немає відповідальної особи '
                            'з користувачем, нагадування не створено.',
                            self.name, summary)
            return False
        if employee.activity_ids.filtered(lambda a: a.summary == summary):
            return False
        employee.activity_schedule(
            'mail.mail_activity_data_todo', date_deadline=deadline,
            user_id=user.id, summary=summary, note=note)
        return True

    @api.model
    def _cron_check_reservation_limits(self):
        """Щоденна перевірка ліміту і строків бронювання (ПКМУ № 1328)."""
        today = date.today()
        for company in self.search([('l10n_ua_critical_enterprise', '=', True)]):
            company._l10n_ua_check_reservation(today)

    def _l10n_ua_check_reservation(self, today):
        self.ensure_one()
        if self.l10n_ua_reservation_exceeded:
            self._l10n_ua_reservation_remind(
                _('Перевищено ліміт бронювання: %s', self.name),
                _('Заброньовано %(reserved)s з %(base)s військовозобов\'язаних '
                  '(%(share).2f %% при ліміті %(limit).2f %%). Протягом %(days)s '
                  'робочих днів з дня перевищення подайте через «Дію» заяву про '
                  'анулювання бронювання (п. 9-2 Порядку № 76 у редакції '
                  'ПКМУ № 1328).',
                  reserved=self.l10n_ua_reserved_count,
                  base=self.l10n_ua_reservation_base or self.l10n_ua_liable_count,
                  share=self.l10n_ua_reservation_share,
                  limit=self.l10n_ua_reservation_limit,
                  days=EXCEEDED_WORKING_DAYS),
                self._l10n_ua_add_working_days(today, EXCEEDED_WORKING_DAYS))
        limit_until = self.l10n_ua_reservation_limit_until
        if (limit_until and limit_until < today
                and self.l10n_ua_limit_end_notified != limit_until):
            self.l10n_ua_limit_end_notified = limit_until
            self._l10n_ua_reservation_remind(
                _('Закінчився збільшений ліміт бронювання: %s', self.name),
                _('Рішення про збільшений ліміт діяло до %(until)s. Протягом '
                  '%(days)s робочих днів анулюйте через «Дію» відстрочки понад '
                  'базову межу і поверніть граничний відсоток у налаштуваннях '
                  'компанії.', until=limit_until.strftime('%d.%m.%Y'),
                  days=LIMIT_ENDED_WORKING_DAYS),
                self._l10n_ua_add_working_days(limit_until, LIMIT_ENDED_WORKING_DAYS))
        critical_until = self.l10n_ua_critical_until
        if (critical_until
                and critical_until <= today + relativedelta(days=CRITICAL_WARN_DAYS)
                and self.l10n_ua_critical_end_notified != critical_until):
            self.l10n_ua_critical_end_notified = critical_until
            self._l10n_ua_reservation_remind(
                _('Закінчується статус критичності: %s', self.name),
                _('Рішення про критичність діє до %s. Подайте документи на '
                  'продовження або підготуйте зняття бронювання працівників.',
                  critical_until.strftime('%d.%m.%Y')),
                critical_until)

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        self.env['hr.tariff.grade']._seed_company_grades(companies)
        return companies

    def _l10n_ua_working_dates(self, date_from, date_to):
        """{date: full-time hours} of the working days between the two dates.

        Monday to Friday at the full-time day of the company's working
        schedule, 8 hours when it has none. The attendance sheet module reads
        the production calendar over this when the company keeps one: the
        calendar is optional, and an empty one is a valid setup — under
        martial law public holidays are working days.

        The timesheet generator and the payslip both read the working days
        here, so a timesheet left as generated brings the payslip the hours
        it would count without one.
        """
        self.ensure_one()
        day_hours = self.resource_calendar_id.hours_per_day or 8.0
        working, current = {}, date_from
        while current <= date_to:
            if current.weekday() < 5:
                working[current] = day_hours
            current += relativedelta(days=1)
        return working

    def _l10n_ua_public_holiday_dates(self, date_from, date_to):
        """The public holidays between the two dates, from the list time off
        is shortened by: those of the company and those of none.

        A holiday is stored in UTC, and a day is a holiday when the holiday
        covers its noon in the time zone of the company's working schedule. A
        holiday entered in local time starts the evening before in UTC, and
        one shipped as a UTC day ends early the next morning in local time;
        read by noon, both fall on their own day.
        """
        self.ensure_one()
        tz = timezone(self.resource_calendar_id.tz or self.env.user.tz or 'UTC')

        def to_utc(day, moment):
            return tz.localize(datetime.combine(day, moment)).astimezone(
                utc).replace(tzinfo=None)

        found = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('company_id', 'in', (self.id, False)),
            ('date_from', '<=', to_utc(date_to, time.max)),
            ('date_to', '>=', to_utc(date_from, time.min)),
        ])
        dates, current = set(), date_from
        # No holiday in the range (an empty list under martial law): nothing
        # to walk through.
        while found and current <= date_to:
            noon = to_utc(current, time(12, 0))
            if any(holiday.date_from <= noon <= holiday.date_to for holiday in found):
                dates.add(current)
            current += relativedelta(days=1)
        return dates
