from odoo import models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _l10n_ua_production_calendar_days(self, date_from, date_to):
        """{date: production calendar line} of the company between the two
        dates; empty where the company keeps no calendar."""
        self.ensure_one()
        calendars = self.env['hr.production.calendar'].search([
            ('year', 'in', list(range(date_from.year, date_to.year + 1))),
            ('company_id', '=', self.id),
        ])
        return {
            line.date: line for line in calendars.line_ids
            if date_from <= line.date <= date_to
        }

    def _l10n_ua_working_dates(self, date_from, date_to):
        """A day the production calendar has is read by its type: a holiday
        or a weekend is not a working day, any other is one of the hours the
        calendar gives it, or of a full day when it gives none. The days the
        calendar does not have are left to the weekdays."""
        working = super()._l10n_ua_working_dates(date_from, date_to)
        day_hours = self.resource_calendar_id.hours_per_day or 8.0
        for day, line in self._l10n_ua_production_calendar_days(
                date_from, date_to).items():
            if line.day_type in ('holiday', 'weekend'):
                working.pop(day, None)
            else:
                working[day] = line.working_hours or day_hours
        return working
