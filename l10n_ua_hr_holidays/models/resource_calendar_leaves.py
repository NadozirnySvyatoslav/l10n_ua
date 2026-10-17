from odoo import _, models


class ResourceCalendarLeaves(models.Model):
    """Public holidays shorten a leave counted in calendar days (art. 5 of
    the Law "On Leaves", art. 73 of the Labour Code). A leave counts its
    holidays when its dates are set; this keeps the leaves already entered
    in step when the holiday list itself is added to, edited or cleared."""
    _inherit = 'resource.calendar.leaves'

    def _reevaluate_leaves(self, time_domain_dict):
        # hr_holidays calls this from create (new values), write (old and
        # new values) and unlink (old values) with the holidays' bounds, and
        # recounts number_of_days of the leaves of the holiday's company. The
        # localization's own durations (calendar and working days, and
        # number_of_days of calendar-day types for holidays of no company)
        # are refreshed here, for the same leaves only.
        Leave = self.env['hr.leave']
        leaves = Leave._l10n_ua_leaves_on_holidays(time_domain_dict or [])
        snapshot = leaves._l10n_ua_duration_snapshot()
        res = super()._reevaluate_leaves(time_domain_dict)
        leaves._l10n_ua_refresh_holiday_durations(
            snapshot, reason=_('the list of public holidays changed'))
        return res
