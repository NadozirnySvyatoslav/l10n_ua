import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

# hr.work.schedule.schedule_type and resource.calendar.ua_schedule_type share
# the same four values, so the mapping is an identity.
UA_SCHEDULE_TYPES = ('standard', 'shift', 'flexible', 'summarized')

# A candidate calendar is only trusted when its weekly norm agrees with the
# schedule's own, within this many hours. Rounding of derived norms (a 6-day
# week gives 6.67 h/day) needs some slack, a wrong calendar is off by much more.
NORM_TOLERANCE_HOURS = 0.5


def _norm_matches(calendar, schedule):
    """Whether the candidate calendar's weekly norm agrees with the schedule.

    hr.work.schedule.resource_calendar_id was documented as an integration
    bridge but never read by any code, so nothing ever validated it — and the
    same holds for a predefined schedule whose hours an HR officer edited
    locally. Both are checked against the schedule's own hours_per_week rather
    than trusted, because accepting a mismatched calendar silently changes the
    employee's payroll norm and leave entitlement.
    """
    if not schedule.hours_per_week:
        return True
    return abs(calendar.hours_per_week - schedule.hours_per_week) <= NORM_TOLERANCE_HOURS


def _attendance_vals_from_lines(schedule):
    """Attendance values built from the schedule's own daily grid, if any.

    Almost no installation has these lines — hr.work.schedule.line was never
    read by any computation and the ten predefined schedules ship without it —
    but a customer who did fill the grid in should keep it.
    """
    vals = []
    for line in schedule.line_ids.filtered(lambda l: l.is_working_day):
        has_break = line.break_from and line.break_to and (
            line.work_from < line.break_from < line.break_to < line.work_to)
        if has_break:
            vals.append({
                'dayofweek': line.day_of_week,
                'day_period': 'morning',
                'hour_from': line.work_from,
                'hour_to': line.break_from,
            })
            vals.append({
                'dayofweek': line.day_of_week,
                'day_period': 'afternoon',
                'hour_from': line.break_to,
                'hour_to': line.work_to,
            })
        elif line.work_to > line.work_from:
            vals.append({
                'dayofweek': line.day_of_week,
                'day_period': 'morning',
                'hour_from': line.work_from,
                'hour_to': line.work_to,
            })
    return vals


def _attendance_vals_uniform(schedule):
    """Even weekly grid derived from working_days_per_week × hours_per_day."""
    days = schedule.working_days_per_week or 0
    hours = schedule.hours_per_day or 0.0
    if not days or not hours or hours > 24.0 or days > 7:
        return []
    return [{
        'dayofweek': str(day),
        'day_period': 'morning',
        'hour_from': 9.0,
        'hour_to': 9.0 + hours,
    } for day in range(days)]


def _weekly_hours(attendances):
    return sum(max(0.0, a['hour_to'] - a['hour_from']) for a in attendances)


def _create_calendar_from_schedule(env, schedule):
    """Build a resource.calendar out of a customer-defined UA schedule.

    A schedule whose pattern does not fit a weekly grid (shift cycles,
    summarized accounting) becomes a core 'flexible' calendar carrying the
    hours explicitly — core then leaves hours_per_week/hours_per_day alone
    instead of recomputing them to zero from an empty attendance list.

    The same applies when a grid exists but contradicts the schedule's own
    weekly norm: a 2/2 cycle cannot be expressed as a week, so its daily rows
    add up to something the payroll never used. The declared norm wins, so
    that nobody's norm changes just because of the upgrade.
    """
    attendances = (_attendance_vals_from_lines(schedule)
                   or _attendance_vals_uniform(schedule))
    if attendances and schedule.hours_per_week:
        grid_hours = _weekly_hours(attendances)
        if abs(grid_hours - schedule.hours_per_week) > NORM_TOLERANCE_HOURS:
            _logger.warning(
                "l10n_ua_hr_contract 20.0.3.0.0: schedule %s (id=%s) declares "
                "%.2f h/week but its daily grid adds up to %.2f; keeping the "
                "declared norm and dropping the grid",
                schedule.name, schedule.id, schedule.hours_per_week,
                grid_hours)
            attendances = []
    vals = {
        'name': schedule.name,
        'ua_code': schedule.code,
        'ua_schedule_type': (schedule.schedule_type
                             if schedule.schedule_type in UA_SCHEDULE_TYPES
                             else 'standard'),
        'ua_is_night_work': schedule.is_night_work,
        'ua_night_start_hour': schedule.night_start_hour,
        'ua_night_end_hour': schedule.night_end_hour,
        'ua_is_hazardous': schedule.is_hazardous,
        'ua_reduced_hours': schedule.reduced_hours,
        'company_id': schedule.company_id.id,
        'attendance_ids': [(5, 0, 0)] + [(0, 0, a) for a in attendances],
    }
    if not attendances:
        vals.update({
            'calendar_type': 'undefined',
            'hours_per_week': schedule.hours_per_week,
            'hours_per_day': schedule.hours_per_day,
        })
    calendar = env['resource.calendar'].create(vals)
    _logger.info(
        "l10n_ua_hr_contract 20.0.3.0.0: created calendar %s (id=%s) from "
        "custom schedule %s (id=%s), %s attendance lines",
        calendar.name, calendar.id, schedule.name, schedule.id,
        len(attendances))
    return calendar


def migrate(cr, version):
    """Map hr.version.work_schedule_ua_id onto core resource_calendar_id.

    Overwrites the version calendar only when it is still the company default.
    A calendar an HR officer set deliberately is left untouched and logged for
    manual review — silently replacing it would change that employee's leave
    entitlement without anyone asking for it.
    """
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    if 'work_schedule_ua_id' not in env['hr.version']._fields:
        # 20.0.4.0.0 dropped hr.work.schedule and the legacy field, so this
        # script has nothing left to read. It can only be reached by an
        # upgrade that jumps over 20.0.3.0.0, which 20.0.4.0.0/pre-migrate
        # refuses precisely because the mapping below would be lost.
        _logger.info(
            "l10n_ua_hr_contract 20.0.3.0.0: legacy work schedules already "
            "removed, nothing to map")
        return

    cr.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables "
        "WHERE table_name = 'hr_work_schedule')")
    if not cr.fetchone()[0]:
        _logger.info(
            "l10n_ua_hr_contract 20.0.3.0.0: no hr_work_schedule table, "
            "nothing to map (clean install)")
        return

    by_code = {}
    for calendar in env['resource.calendar'].search([('ua_code', '!=', False)]):
        by_code.setdefault(calendar.ua_code, calendar)

    created = {}
    skipped = []
    already_correct = 0
    migrated = 0

    versions = env['hr.version'].search([('work_schedule_ua_id', '!=', False)])
    for ver in versions:
        schedule = ver.work_schedule_ua_id

        target = None
        rejected = []
        for candidate in (created.get(schedule.id),
                          schedule.resource_calendar_id,
                          by_code.get(schedule.code)):
            if not candidate:
                continue
            if _norm_matches(candidate, schedule):
                target = candidate
                break
            rejected.append((candidate.id, candidate.hours_per_week))

        if not target:
            if rejected:
                _logger.warning(
                    "l10n_ua_hr_contract 20.0.3.0.0: schedule %s (id=%s, "
                    "%.2f h/week) had candidate calendars with a different "
                    "norm %s; building a calendar from the schedule instead",
                    schedule.name, schedule.id, schedule.hours_per_week,
                    rejected)
            target = _create_calendar_from_schedule(env, schedule)
            created[schedule.id] = target

        if ver.resource_calendar_id == target:
            already_correct += 1
            continue

        company_default = ver.company_id.resource_calendar_id
        if ver.resource_calendar_id and ver.resource_calendar_id != company_default:
            skipped.append((ver.id, ver.resource_calendar_id.id, target.id))
            continue

        ver.resource_calendar_id = target
        migrated += 1

    env['hr.version'].flush_model(['resource_calendar_id'])

    if skipped:
        _logger.warning(
            "l10n_ua_hr_contract 20.0.3.0.0: %s versions kept a custom "
            "calendar; migration skipped them, manual review required "
            "(version_id, current_calendar_id, intended_calendar_id): %s",
            len(skipped), skipped)

    _logger.info(
        "l10n_ua_hr_contract 20.0.3.0.0: %s versions mapped, %s already "
        "correct, %s skipped, %s calendars built from schedules",
        migrated, already_correct, len(skipped), len(created))
