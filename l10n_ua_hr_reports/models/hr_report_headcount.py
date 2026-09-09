from odoo import models, fields, api
from calendar import monthrange
from collections import Counter
from datetime import date, timedelta


class HrReportHeadcount(models.Model):
    """Average Headcount Report (Середньооблікова чисельність)

    Calculates average headcount according to Ukrainian methodology
    (Order of State Statistics Committee #286, 28.09.2005).
    """
    _name = 'hr.report.headcount'
    _description = 'Average Headcount Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, month desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True
    )
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year,
        tracking=True
    )
    month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'),
        ('4', 'April'), ('5', 'May'), ('6', 'June'),
        ('7', 'July'), ('8', 'August'), ('9', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True, tracking=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # Report results
    avg_headcount = fields.Float(
        string='Average Headcount (Full-time)',
        digits=(10, 2),
        help='Average headcount of full-time employees'
    )
    avg_headcount_full = fields.Float(
        string='Average Headcount (All)',
        digits=(10, 2),
        help='Average headcount including part-time (FTE equivalent)'
    )

    total_calendar_days = fields.Integer(
        string='Calendar Days',
        help='Total calendar days in the period'
    )

    line_ids = fields.One2many(
        'hr.report.headcount.line',
        'report_id',
        string='Daily Data'
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Notes')

    @api.depends('year', 'month')
    def _compute_name(self):
        month_names = {
            '1': 'Січень', '2': 'Лютий', '3': 'Березень',
            '4': 'Квітень', '5': 'Травень', '6': 'Червень',
            '7': 'Липень', '8': 'Серпень', '9': 'Вересень',
            '10': 'Жовтень', '11': 'Листопад', '12': 'Грудень',
        }
        for rec in self:
            month_name = month_names.get(rec.month, rec.month)
            rec.name = f'Середньооблікова чисельність {month_name} {rec.year}'

    def action_generate(self):
        """Generate daily headcount data and calculate average"""
        self.ensure_one()
        self.line_ids.unlink()

        month_int = int(self.month)
        days_in_month = monthrange(self.year, month_int)[1]

        total_headcount = 0
        total_fte = 0

        for day in range(1, days_in_month + 1):
            current_date = date(self.year, month_int, day)

            # Count employees who were employed on this date
            headcount, fte = self._count_employees_on_date(current_date)

            self.env['hr.report.headcount.line'].create({
                'report_id': self.id,
                'date': current_date,
                'headcount': headcount,
                'fte_count': fte,
            })

            total_headcount += headcount
            total_fte += fte

        # Calculate average
        self.write({
            'avg_headcount': round(total_headcount / days_in_month, 2),
            'avg_headcount_full': round(total_fte / days_in_month, 2),
            'total_calendar_days': days_in_month,
            'state': 'generated',
        })

        return True

    def _count_employees_on_date(self, check_date):
        """Count unique employees on a specific date.

        For each employee we pick the version whose date_version is the
        greatest among `date_version <= check_date` (and treat NULL as
        "no scheduled change" → use only as fallback when no dated
        version exists).
        """
        headcount = 0
        fte = 0.0

        versions = self.env['hr.version'].with_context(active_test=False).search([
            ('employee_id.company_id', '=', self.company_id.id),
            ('contract_date_start', '<=', check_date),
            '|',
            ('contract_date_end', '=', False),
            ('contract_date_end', '>', check_date),
        ])

        # Pick one version per employee: greatest date_version that is <= check_date.
        # NULL date_version is treated as "−infinity" so any dated version wins;
        # this is robust regardless of SQL NULL-ordering.
        by_employee = {}
        for v in versions:
            if v.date_version and v.date_version > check_date:
                # Future-scheduled version (e.g., promotion next month) — skip.
                continue
            emp_id = v.employee_id.id
            existing = by_employee.get(emp_id)
            if existing is None:
                by_employee[emp_id] = v
                continue
            # Compare: dated version always beats NULL; same date → greater id.
            new_key = (v.date_version or date.min, v.id)
            cur_key = (existing.date_version or date.min, existing.id)
            if new_key > cur_key:
                by_employee[emp_id] = v

        actual_versions = self.env['hr.version'].browse(
            [v.id for v in by_employee.values()]
        )

        # The staffing line is resolved for `check_date` rather than read off
        # `version.staffing_line_id`. That field answers for the version's own
        # period, and for the ordinary open-ended Ukrainian contract that means
        # today: a report for March would then count the staff units the
        # position carries in September. Worse, the field is computed and not
        # stored, so within one transaction every day of the month would share
        # the same answer.
        #
        # `with_company`, not `sudo`: the staffing table is read through a rule
        # on the companies ticked in the switcher, so a report for a company
        # left out would silently resolve nothing and count everyone as one
        # full unit. Stating the report's own company raises instead of
        # miscounting.
        Staffing = self.env['hr.staffing.table'].with_company(self.company_id)
        staffing_keys = {
            version.id: (version.company_id.id, version.department_id.id,
                         version.job_id.id, check_date)
            for version in actual_versions
        }
        staffing_lines = Staffing._resolve_batch(list(staffing_keys.values()))

        # Two passes: who is counted on this date, and only then at what
        # rate. The rate of one person depends on how many others hold the
        # same post that day, so the set has to be closed before any of it
        # can be measured.
        counted = []
        for version in actual_versions:
            employee = version.employee_id

            # Effective end of employment for this employee.
            # Primary signal: contract_date_end on the picked version
            # (set by _apply_dismissal across all versions).
            # Fallback: employee.departure_date — standard Odoo field set
            # by the built-in departure wizard and by _apply_dismissal.
            # Catches legacy dismissals that archived the employee +
            # set departure_date but never propagated contract_date_end
            # to hr.version.
            effective_end = version.contract_date_end
            if not effective_end and 'departure_date' in employee._fields:
                effective_end = employee.departure_date

            if effective_end and effective_end <= check_date:
                # Employee was terminated on or before check_date.
                continue

            # Safety net for broken data: an archived employee with no
            # termination date anywhere (manual archive bypassing both
            # _apply_dismissal and Odoo's departure wizard). We don't
            # know when they actually left, so we exclude conservatively
            # — better than counting them forever.
            # Trade-off: past-period reports for such records will
            # under-count; fix the data (set departure_date or run a
            # confirmed dismissal order) to restore them.
            if not employee.active and not effective_end:
                continue

            counted.append(version)

        # How many of the people counted today hold each post. Taken from the
        # set above rather than from `filled_units`, which answers for today
        # and sums the very `work_rate` this is standing in for.
        occupants = Counter(staffing_keys[version.id] for version in counted)

        for version in counted:
            work_rate = version.work_rate or 0.0
            if not work_rate:
                # `units` is what the position is worth, not what one person
                # is: a post of two units held by two people is one full rate
                # each, and counting two apiece reported four. So the units of
                # the post are divided among those holding it — which also
                # gives job-sharing (one unit, two people) a half rate each —
                # and no single guess exceeds a full rate, because nothing
                # here says anybody works more than one.
                #
                # This only ever runs where the version carries no rate of its
                # own; `work_rate` defaults to 1.0, so it means missing data,
                # and a post of half a unit is the one case the staffing table
                # answers better than that default does.
                key = staffing_keys[version.id]
                staffing = staffing_lines.get(key)
                held = occupants.get(key, 0)
                work_rate = min(staffing.units / held, 1.0) \
                    if staffing and staffing.units and held else 1.0

            if work_rate >= 1.0:
                headcount += 1
            fte += work_rate

        return headcount, fte

    def action_draft(self):
        self.write({'state': 'draft'})

    _unique_year_month_company_id = models.Constraint(
        'unique(year, month, company_id)',
        'Headcount report for this period already exists!',
    )


class HrReportHeadcountLine(models.Model):
    _name = 'hr.report.headcount.line'
    _description = 'Headcount Report Daily Line'
    _order = 'date'

    report_id = fields.Many2one(
        'hr.report.headcount',
        string='Report',
        required=True,
        ondelete='cascade'
    )
    date = fields.Date(string='Date', required=True)
    day_of_week = fields.Char(
        string='Day',
        compute='_compute_day_of_week'
    )
    headcount = fields.Integer(
        string='Headcount',
        help='Number of full-time employees'
    )
    fte_count = fields.Float(
        string='FTE',
        digits=(10, 2),
        help='Full-time equivalent count'
    )

    @api.depends('date')
    def _compute_day_of_week(self):
        days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']
        for rec in self:
            if rec.date:
                rec.day_of_week = days[rec.date.weekday()]
            else:
                rec.day_of_week = ''
