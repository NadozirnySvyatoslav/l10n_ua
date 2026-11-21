from datetime import date as Date

from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

# Martial law was imposed on 24.02.2022 (Указ Президента №64/2022). While it
# lasts, the days off of art. 73 КЗпП do not apply (Закон №2136-IX, ст. 12):
# public holidays are ordinary working days.
MARTIAL_LAW_START = Date(2022, 2, 24)


def orthodox_easter(year):
    """Orthodox Easter Sunday (Gregorian date) of the year.

    Julian computus (Meeus), then shifted to the Gregorian calendar. The
    calendar reform of the OCU (2023) moved the fixed feasts only: Easter is
    still reckoned by the Julian computus, so it stays a common date with the
    other Orthodox churches.
    """
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    # Julian to Gregorian: 13 days in 1900–2099, one more per century not
    # divisible by 400 after that.
    shift = year // 100 - year // 400 - 2
    return Date(year, month, day) + relativedelta(days=shift)


class HrProductionCalendar(models.Model):
    _name = 'hr.production.calendar'
    _description = 'Production Calendar'
    _order = 'year desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    martial_law = fields.Boolean(
        string='Martial Law (holidays are working days)',
        default=True,
        help='Under martial law (since 24.02.2022) public holidays are not '
             'days off: they are generated as ordinary working days, with no '
             'shortened pre-holiday day. Untick once martial law is lifted.'
    )

    line_ids = fields.One2many(
        'hr.production.calendar.line',
        'calendar_id',
        string='Calendar Lines'
    )
    
    total_days = fields.Integer(
        string='Total Days',
        compute='_compute_totals',
        store=True
    )
    working_days = fields.Integer(
        string='Working Days',
        compute='_compute_totals',
        store=True
    )
    holidays = fields.Integer(
        string='Holidays',
        compute='_compute_totals',
        store=True
    )
    working_hours = fields.Float(
        string='Working Hours',
        compute='_compute_totals',
        store=True
    )

    @api.depends('year')
    def _compute_name(self):
        for rec in self:
            rec.name = f'Виробничий календар {rec.year}'

    @api.depends('line_ids.is_working_day', 'line_ids.working_hours')
    def _compute_totals(self):
        for rec in self:
            rec.total_days = len(rec.line_ids)
            rec.working_days = len(rec.line_ids.filtered('is_working_day'))
            rec.holidays = len(rec.line_ids.filtered(lambda l: l.day_type == 'holiday'))
            rec.working_hours = sum(rec.line_ids.mapped('working_hours'))

    def action_generate_calendar(self):
        """Generate calendar for the year"""
        self.ensure_one()
        self.line_ids.unlink()
        
        # Ukrainian public holidays
        holidays = self._get_ua_holidays(self.year)
        # Under martial law they are working days; the name stays on the
        # line for reference only.
        days_off = {
            day: name for day, name in holidays.items()
            if not (self.martial_law and day >= MARTIAL_LAW_START)
        }
        transferred = self._get_transferred_days_off(days_off)
        
        date = fields.Date.from_string(f'{self.year}-01-01')
        year_end = fields.Date.from_string(f'{self.year}-12-31')
        
        lines = []
        while date <= year_end:
            is_weekend = date.weekday() >= 5
            is_holiday = date in days_off
            
            if is_holiday:
                day_type = 'holiday'
                is_working = False
                hours = 0
            elif date in transferred:
                day_type = 'transferred'
                is_working = False
                hours = 0
            elif is_weekend:
                day_type = 'weekend'
                is_working = False
                hours = 0
            else:
                day_type = 'working'
                is_working = True
                hours = 8.0
                
                # Check for pre-holiday shortened day
                next_day = date + relativedelta(days=1)
                if next_day in days_off and is_working:
                    hours = 7.0
            
            lines.append({
                'calendar_id': self.id,
                'date': date,
                'day_type': day_type,
                'is_working_day': is_working,
                'working_hours': hours,
                'holiday_name': holidays.get(date, '') or transferred.get(date, ''),
            })
            
            date += relativedelta(days=1)
        
        self.env['hr.production.calendar.line'].create(lines)
        return True

    def _get_ua_holidays(self, year):
        """Get Ukrainian public holidays for the year (art. 73 КЗпП).

        Since 2023 (Закон №3005-IX of 14.07.2023) Christmas is 25 December
        only, 8 May is the Day of Remembrance and Victory over Nazism (9 May
        is no longer a holiday) and the Defenders Day is 1 October. Easter
        and Trinity (49 days after it) are movable, see orthodox_easter().
        """
        easter = orthodox_easter(year)
        holidays = {
            Date(year, 1, 1): 'Новий рік',
            Date(year, 3, 8): 'Міжнародний жіночий день',
            Date(year, 5, 1): 'День праці',
            Date(year, 6, 28): 'День Конституції України',
            Date(year, 8, 24): 'День Незалежності України',
            Date(year, 12, 25): 'Різдво Христове',
            easter: 'Великдень (Пасха)',
            easter + relativedelta(days=49): 'Трійця',
        }
        if year >= 2023:
            holidays.update({
                Date(year, 5, 8): 'День пам\'яті та перемоги над нацизмом '
                                  'у Другій світовій війні 1939–1945 років',
                Date(year, 10, 1): 'День захисників і захисниць України',
            })
        else:
            holidays.update({
                Date(year, 1, 7): 'Різдво Христове (за юліанським календарем)',
                Date(year, 5, 9): 'День перемоги над нацизмом у Другій світовій війні',
                Date(year, 10, 14): 'День захисників і захисниць України',
            })
        return holidays

    @api.model
    def _get_transferred_days_off(self, days_off):
        """Days off moved from a holiday that falls on a weekend.

        Art. 67 КЗпП: when a holiday coincides with a day off, the day off
        moves to the next working day after the holiday. Easter and Trinity
        always fall on a Sunday, so without this they would never change the
        norm. Returns ``{date: name}``.
        """
        transferred = {}
        for day in sorted(days_off):
            if day.weekday() < 5:
                continue
            target = day + relativedelta(days=1)
            while (target.weekday() >= 5 or target in days_off
                   or target in transferred):
                target += relativedelta(days=1)
            transferred[target] = 'Перенесений вихідний (%s)' % days_off[day]
        return transferred

    _unique_year_company_id = models.Constraint(
        'unique(year, company_id)',
        'Production calendar for this year already exists!',
    )


class HrProductionCalendarLine(models.Model):
    _name = 'hr.production.calendar.line'
    _description = 'Production Calendar Line'
    _order = 'date'

    calendar_id = fields.Many2one(
        'hr.production.calendar',
        string='Calendar',
        required=True,
        ondelete='cascade'
    )
    date = fields.Date(string='Date', required=True)
    
    day_type = fields.Selection([
        ('working', 'Working Day'),
        ('weekend', 'Weekend'),
        ('holiday', 'Public Holiday'),
        ('transferred', 'Transferred Day'),
    ], string='Day Type', required=True, default='working')
    
    is_working_day = fields.Boolean(string='Working Day')
    working_hours = fields.Float(string='Working Hours')
    holiday_name = fields.Char(string='Holiday Name')
    
    month = fields.Integer(
        string='Month',
        compute='_compute_month',
        store=True
    )
    day_of_week = fields.Integer(
        string='Day of Week',
        compute='_compute_month',
        store=True
    )

    @api.depends('date')
    def _compute_month(self):
        for line in self:
            if line.date:
                line.month = line.date.month
                line.day_of_week = line.date.weekday()
            else:
                line.month = 0
                line.day_of_week = 0
