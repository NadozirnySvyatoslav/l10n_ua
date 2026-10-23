from datetime import datetime, time

from dateutil.relativedelta import relativedelta
from pytz import timezone, utc

from odoo import api, fields, models


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
