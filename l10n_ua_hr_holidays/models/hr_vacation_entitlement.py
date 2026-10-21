from collections import Counter
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from pytz import timezone, utc

from odoo import api, models

from .hr_leave_type import COMPENSATED_LEAVE_CATEGORIES

# Absences that do not count towards the seniority giving the right to the
# annual basic leave: the partly paid childcare leave, the unpaid childcare
# leave and the unpaid leave taken abroad or as an internally displaced person
# under martial law. Sick and maternity leave, paid time off and the other
# unpaid leave count. The same seniority rules the additional leave that is not
# tied to working conditions.
BASIC_EXCLUDED_CATEGORIES = ('childcare', 'unpaid_abroad', 'unpaid_childcare')

# Additional leave earned only by the days actually worked in the conditions
# it is granted for. Of the absences, only the annual basic leave and these
# same additional leaves count.
WORKED_TIME_CATEGORIES = ('annual_hazardous', 'annual_special', 'annual_irregular')
WORKED_TIME_COUNTED_CATEGORIES = ('annual_basic',) + WORKED_TIME_CATEGORIES

# Absences that do not count as a day of seniority for the additional leave of
# workers with children.
CHILDREN_EXCLUDED_CATEGORIES = ('maternity', 'childcare')

# Days earned up to this date are paid out from a different average, so a
# period spanning it is reported in two parts.
SPLIT_DATE = date(2024, 1, 1)



class HrVacationEntitlement(models.AbstractModel):
    """Unused vacation days of an employee as of a date.

    One calculation for every document that quotes them — the dismissal
    order's compensation and the remaining vacation certificate — so they can
    never disagree.

    For each leave type paid out on dismissal it walks the accounting periods
    from the hire date up to the date asked for:

    * the right for a period is the employee's full norm for it (the
      balance's Entitled Days), in proportion to the calendar days of the
      period that count as seniority; the additional leave of workers with
      children is granted in full for any calendar year with a day of
      seniority in it;
    * the days used are charged against the oldest right first, so what is
      left belongs to the most recent periods;
    * transfer limits do not apply: unused days of every past period are
      due, whatever the leave type carries over;
    * a negative balance of one type never reduces another.
    """
    _name = 'hr.vacation.entitlement'
    _description = 'Vacation Entitlement'

    @api.model
    def _compensated_days(self, employee, as_of):
        """Days of unused vacation to pay out on a dismissal on as_of: the
        sum of every leave type's days, unrounded. The total is rounded once,
        by compensable_vacation_days(), wherever a whole number is shown."""
        return sum(line['remaining'] for line in self._unused_vacation(employee, as_of))

    @api.model
    def _unused_vacation(self, employee, as_of):
        """Per leave type, the periods and totals of the unused vacation of
        `employee` as of `as_of` (inclusive).

        Returns a list of dicts, one per leave type, in the order the types
        are listed on the certificate:

        * leave_type: the hr.leave.type;
        * rows: the periods, oldest first, each a dict with date_from,
          date_to, is_current, is_carried, is_split (one of the two parts of
          a period spanning SPLIT_DATE), entitled (the norm for the period),
          accrued (earned up to as_of), used, remaining and usable;
        * accrued, used, remaining, usable: the type's totals, remaining and
          usable never below zero;
        * pro_rated_first_year: the current period is the first work year
          before six months of work, so only the days earned may be taken;
        * remaining_before_split: the part of the remaining days earned
          before SPLIT_DATE.
        """
        employee.ensure_one()
        hire = employee._get_vacation_anchor_date()
        if not hire or not as_of or as_of < hire:
            return []
        Balance = self.env['hr.vacation.balance']
        balances = Balance.search([
            ('employee_id', '=', employee.id),
            ('leave_type_id.ua_leave_category', 'in', COMPENSATED_LEAVE_CATEGORIES),
            ('period_start', '<=', as_of),
        ], order='period_start, id')
        basic_type = self._basic_leave_type(employee, balances)
        leave_types = balances.leave_type_id | basic_type

        periods_by_type = {}
        for leave_type in leave_types:
            periods = self._periods(
                employee, leave_type,
                balances.filtered(lambda b: b.leave_type_id == leave_type),
                hire, as_of, backfill=leave_type == basic_type)
            if periods:
                periods_by_type[leave_type] = periods
        if not periods_by_type:
            return []

        first_day = min(p['date_from'] for ps in periods_by_type.values() for p in ps)
        last_day = max(p['date_to'] for ps in periods_by_type.values() for p in ps)
        holidays = self._public_holiday_dates(employee, first_day, last_day)
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('request_date_from', '<=', as_of),
            ('request_date_to', '>=', min(first_day, hire)),
        ])
        absences = self._absence_dates(leaves)

        order = {category: index for index, category in enumerate(COMPENSATED_LEAVE_CATEGORIES)}
        result = []
        for leave_type in sorted(periods_by_type, key=lambda t: (
                order.get(t.ua_leave_category, len(order)), t.name or '', t.id)):
            used = sum(self._days_used(leave, as_of, holidays) for leave in leaves.filtered(
                lambda l: l.holiday_status_id == leave_type))
            result.append(self._settle(
                leave_type, periods_by_type[leave_type], used,
                hire, as_of, holidays, absences))
        return result

    # ------------------------------------------------------------------
    # Periods
    # ------------------------------------------------------------------

    @api.model
    def _basic_leave_type(self, employee, balances):
        """The annual basic leave type every employee has a right to, even
        without a single balance recorded: the one most of the employee's
        balances are of, otherwise the company's own, otherwise a shared one.

        The other types are only counted for the periods a balance exists
        for — the balance is what records the right to them."""
        basic = balances.filtered(
            lambda b: b.leave_type_id.ua_leave_category == 'annual_basic')
        if basic:
            counts = Counter(basic.leave_type_id.ids)
            return self.env['hr.leave.type'].browse(
                max(counts, key=lambda type_id: (counts[type_id], -type_id)))
        candidates = self.env['hr.leave.type'].search([
            ('ua_leave_category', '=', 'annual_basic'),
            ('company_id', 'in', [employee.company_id.id, False]),
        ], order='id')
        own = candidates.filtered(lambda t: t.company_id == employee.company_id)
        return (own or candidates)[:1]

    @api.model
    def _periods(self, employee, leave_type, balances, hire, as_of, backfill=False):
        """The accounting periods of one leave type up to as_of, oldest first.

        Each recorded balance is a period. With `backfill`, the periods from
        the hire date that have no balance are added with the type's norm,
        without creating any record. The days carried into the earliest
        balance (from another company, or entered by hand) are kept, unless
        that balance is a duplicate left out; the ones the later balances
        show are left out, since every period is counted here on its own."""
        # Only the earliest balance holds days carried in by hand or from
        # another company; the later ones show what the chain carried over.
        first = balances.sorted(lambda b: (b.period_start, b.id))[:1]
        balances = self._distinct_balances(employee, leave_type, balances)
        periods = [{
            'date_from': balance.period_start,
            'date_to': balance.period_end,
            'norm': balance.entitled_days or 0.0,
        } for balance in balances]
        if backfill:
            Balance = self.env['hr.vacation.balance']
            cursor, guard = hire, 0
            while cursor <= as_of and guard < 200:
                guard += 1
                start, end, _index = Balance._get_period_for(employee, leave_type, cursor)
                if not start:
                    break
                if not any(p['date_from'] <= end and p['date_to'] >= start for p in periods):
                    periods.append({
                        'date_from': start,
                        'date_to': end,
                        'norm': float(leave_type.annual_days or 0),
                    })
                cursor = end + timedelta(days=1)
        periods.sort(key=lambda p: p['date_from'])
        carried = (first.carried_over or 0.0) if first in balances else 0.0
        if carried:
            next(p for p in periods if p['date_from'] == first.period_start)['carried'] = carried
        return periods

    @api.model
    def _distinct_balances(self, employee, leave_type, balances):
        """The balances of one leave type with no two covering the same days.

        A balance left from an earlier hire date overlaps the one of the
        current work year; counting both would grant the same days twice. Of
        two overlapping balances the one starting where the period of the
        current hire date starts is kept, otherwise the newer one."""
        Balance = self.env['hr.vacation.balance']

        def canonical(balance):
            start = Balance._get_period_for(employee, leave_type, balance.period_start)[0]
            return start == balance.period_start

        kept = []
        for balance in balances.sorted(lambda b: (b.period_start, b.id)):
            clash = next((k for k in kept if k.period_start <= balance.period_end
                          and k.period_end >= balance.period_start), None)
            if not clash:
                kept.append(balance)
            elif (canonical(balance), balance.id) > (canonical(clash), clash.id):
                kept[kept.index(clash)] = balance
        return Balance.browse([b.id for b in kept]).sorted(lambda b: (b.period_start, b.id))

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------

    @api.model
    def _public_holiday_dates(self, employee, date_from, date_to):
        """The public holidays between the two dates, from the employee's
        company and working schedule or shared ones.

        A day is a holiday when a holiday covers its noon in the schedule's
        time zone, so a holiday stored in UTC falls on its own local day."""
        calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
        tz = timezone(calendar.tz or self.env.user.tz or 'UTC')

        def to_utc(day, moment):
            return tz.localize(datetime.combine(day, moment)).astimezone(utc).replace(tzinfo=None)

        found = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('company_id', 'in', [employee.company_id.id, False]),
            ('calendar_id', 'in', [calendar.id, False]),
            ('date_from', '<=', to_utc(date_to, time.max)),
            ('date_to', '>=', to_utc(date_from, time.min)),
        ])
        dates, day = set(), date_from
        while found and day <= date_to:
            noon = to_utc(day, time(12))
            if any(h.date_from <= noon <= h.date_to for h in found):
                dates.add(day)
            day += timedelta(days=1)
        return dates

    @api.model
    def _days_used(self, leave, as_of, holidays):
        """Calendar days of the time off taken up to and including as_of.

        A time off running past the date counts only its days up to it: the
        rest is not used yet (or never will be, on a dismissal during the
        leave). The public holidays inside it are not counted, the same as
        in its own length."""
        if not leave.request_date_to or leave.request_date_to <= as_of:
            return leave.calendar_days
        days, day = 0, leave.request_date_from
        while day <= as_of:
            if day not in holidays:
                days += 1
            day += timedelta(days=1)
        return days

    @api.model
    def _absence_dates(self, leaves):
        """{category: set of dates} of the given time off."""
        absences = {}
        for leave in leaves:
            category = leave.holiday_status_id.ua_leave_category
            if not category or not leave.request_date_from or not leave.request_date_to:
                continue
            dates = absences.setdefault(category, set())
            day = leave.request_date_from
            while day <= leave.request_date_to:
                dates.add(day)
                day += timedelta(days=1)
        return absences

    @api.model
    def _excluded_dates(self, leave_type, absences):
        """Dates that do not count as seniority for the given leave type."""
        category = leave_type.ua_leave_category
        if category in WORKED_TIME_CATEGORIES:
            excluded = [c for c in absences if c not in WORKED_TIME_COUNTED_CATEGORIES]
        elif category == 'social_children':
            excluded = CHILDREN_EXCLUDED_CATEGORIES
        else:
            excluded = BASIC_EXCLUDED_CATEGORIES
        dates = set()
        for c in excluded:
            dates |= absences.get(c, set())
        return dates

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    @api.model
    def _settle(self, leave_type, periods, used, hire, as_of, holidays, absences):
        excluded = self._excluded_dates(leave_type, absences)
        is_children = leave_type.ua_leave_category == 'social_children'

        def days(date_from, date_to, skip=frozenset()):
            if date_from > date_to:
                return 0
            count, day = 0, date_from
            while day <= date_to:
                if day not in holidays and day not in skip:
                    count += 1
                day += timedelta(days=1)
            return count

        rows = []
        pro_rated_first_year = False
        for period in periods:
            if period.get('carried'):
                rows.append({
                    'date_from': period['date_from'],
                    'date_to': period['date_to'],
                    'is_current': False,
                    'is_carried': True,
                    'is_split': False,
                    'entitled': period['carried'],
                    'accrued': period['carried'],
                    'usable_cap': period['carried'],
                })
            start, end, norm = period['date_from'], period['date_to'], period['norm']
            base = days(start, end) or 1
            seniority_from = max(start, hire)
            seniority_to = min(end, as_of)
            is_current = start <= as_of <= end
            # Before six months of continuous work in the first work year
            # only the days earned so far may be taken; a few groups of
            # employees may take the whole year's leave, which is left to HR.
            too_early = (not is_children and start <= hire
                         and as_of < hire + relativedelta(months=6))
            parts = [(start, end)]
            if start < SPLIT_DATE <= end:
                parts = [(start, SPLIT_DATE - timedelta(days=1)), (SPLIT_DATE, end)]
            for part_from, part_to in parts:
                entitled = norm * days(part_from, part_to) / base
                if is_children:
                    worked = days(seniority_from, seniority_to, excluded)
                    accrued = norm if worked else 0.0
                    entitled = norm
                else:
                    worked = days(max(part_from, seniority_from),
                                  min(part_to, seniority_to), excluded)
                    accrued = norm * worked / base
                part_current = is_current and part_from <= as_of <= part_to
                if part_current:
                    usable_cap = accrued if too_early else entitled
                    pro_rated_first_year = pro_rated_first_year or too_early
                else:
                    usable_cap = accrued
                if part_from > as_of:
                    continue
                rows.append({
                    'date_from': part_from,
                    'date_to': part_to,
                    'is_current': part_current,
                    'is_carried': False,
                    'is_split': len(parts) > 1,
                    'entitled': entitled,
                    'accrued': accrued,
                    'usable_cap': usable_cap,
                })

        for key, cap in (('used', 'accrued'), ('usable_used', 'usable_cap')):
            rest = used
            for row in rows:
                take = min(row[cap], rest) if rest > 0 else 0.0
                row[key] = take
                rest -= take
            if rest > 0 and rows:
                rows[-1][key] += rest
        for row in rows:
            row['remaining'] = row['accrued'] - row['used']
            row['usable'] = row['usable_cap'] - row['usable_used']

        accrued = sum(row['accrued'] for row in rows)
        remaining = max(0.0, accrued - used)
        usable = max(0.0, sum(row['usable_cap'] for row in rows) - used)
        return {
            'leave_type': leave_type,
            'rows': rows,
            'accrued': accrued,
            'used': used,
            'remaining': remaining,
            'usable': usable,
            'pro_rated_first_year': pro_rated_first_year,
            'remaining_before_split': max(0.0, sum(
                row['remaining'] for row in rows if row['date_to'] < SPLIT_DATE)),
        }
