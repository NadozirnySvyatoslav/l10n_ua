import calendar
from datetime import date as Date, timedelta

from odoo import api, models, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class HrTariffGrade(models.Model):
    _name = 'hr.tariff.grade'
    _description = 'Tariff Grade'
    _inherit = ['mail.thread']
    _order = 'date_from desc, grade'

    name = fields.Char(string='Name', required=True)
    grade = fields.Integer(string='Grade', required=True)
    coefficient = fields.Float(string='Coefficient', digits=(16, 4), default=1.0,
                               tracking=True)
    hourly_rate = fields.Monetary(
        string='Hourly Rate', currency_field='currency_id', tracking=True,
        help='Hourly tariff rate of the grade, as stated in the collective '
             'agreement. Monthly salaries belong to the staffing table.')
    # The currency of the company that keeps the grade, not of the one in the
    # switcher: a rate of another company would otherwise be shown, rounded
    # and compared in the wrong money.
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(string='Active', default=True)
    # Every company keeps its own grades, and a rate is in force for a period.
    # Monthly salaries are not kept here: they are stated in the staffing table.
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    date_from = fields.Date(
        string='Valid From', required=True, default=fields.Date.context_today,
        tracking=True)
    date_to = fields.Date(string='Valid To', tracking=True)
    computed_rate = fields.Monetary(
        string='Computed Rate', compute='_compute_computed_rate',
        currency_field='currency_id',
        help='Base tariff rate × the coefficient of this grade (art. 96 of '
             'the Labour Code), for comparison with the hourly rate of the '
             'collective agreement, which may differ from it, for example by '
             'rounding.')
    rate_diff = fields.Monetary(
        string='Difference', compute='_compute_computed_rate',
        currency_field='currency_id',
        help='Hourly rate minus computed rate. Any difference, down to a '
             'kopiyka, is highlighted.')

    _grade_uniq = models.Constraint(
        'unique(company_id, grade, date_from)',
        'Tariff grade must be unique for a company and a start date!',
    )

    def _first_grade(self):
        """Grade 1 of the same company in force on this grade's start date."""
        self.ensure_one()
        return self._grade_on(1, self.date_from) if self.grade != 1 else self

    def _grade_on(self, grade, on_date):
        return self.search([
            ('company_id', '=', self.company_id.id),
            ('grade', '=', grade),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], limit=1)

    def _formula_rate(self, first_rate):
        amount = first_rate * self.coefficient
        return self.currency_id.round(amount) if self.currency_id else round(amount, 2)

    def _first_grade_rates(self):
        """First-grade rate for each company and start date of this set.

        One query for the whole set: a list of grades holds fifteen of them
        per company and period, and a search each would be as many queries.
        """
        needed = {
            (grade.company_id.id, grade.date_from) for grade in self
            if grade.grade != 1 and grade.company_id and grade.date_from
        }
        if not needed:
            return {}
        first_grades = self.search([
            ('company_id', 'in', [company_id for company_id, _date in needed]),
            ('grade', '=', 1),
        ], order='date_from')
        rates = {}
        for company_id, date_from in needed:
            in_force = first_grades.filtered(
                lambda first: first.company_id.id == company_id
                and first.date_from <= date_from
                and (not first.date_to or first.date_to >= date_from))
            # Ordered by start date, so the last one is the one in force.
            rates[(company_id, date_from)] = in_force[-1:].hourly_rate
        return rates

    @api.depends('coefficient', 'company_id', 'date_from', 'grade', 'hourly_rate')
    def _compute_computed_rate(self):
        rates = self._first_grade_rates()
        for grade in self:
            first_rate = grade.hourly_rate if grade.grade == 1 else rates.get(
                (grade.company_id.id, grade.date_from), 0.0)
            grade.computed_rate = grade._formula_rate(first_rate)
            # Rounded to the kopiyka, so float noise never shows as a difference.
            grade.rate_diff = round(grade.hourly_rate - grade.computed_rate, 2)

    @api.onchange('coefficient', 'grade', 'date_from', 'company_id')
    def _onchange_fill_rate(self):
        # A rate not entered yet takes the formula.
        if self.grade != 1 and float_is_zero(self.hourly_rate, precision_digits=2):
            self.hourly_rate = self.computed_rate

    def _fill_following_rates(self, old_rate):
        """Carry a new first-grade rate to the grades still following it.

        These are the other grades of the company starting within the period
        of this grade 1. A grade follows while its rate is not entered yet or
        still equals the old first-grade rate × coefficient; a rate that
        differs was agreed otherwise and stays as it is.
        """
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('grade', '!=', 1),
            ('date_from', '>=', self.date_from),
        ]
        if self.date_to:
            domain.append(('date_from', '<=', self.date_to))
        for grade in self.search(domain):
            if float_is_zero(grade.hourly_rate, precision_digits=2) or float_compare(
                    grade.hourly_rate, grade._formula_rate(old_rate),
                    precision_digits=2) == 0:
                grade.hourly_rate = grade._formula_rate(self.hourly_rate)
        self.invalidate_model(['computed_rate', 'rate_diff'])

    @api.model_create_multi
    def create(self, vals_list):
        grades = super().create(vals_list)
        for grade in grades.sorted('grade'):
            if grade.grade == 1:
                grade._fill_following_rates(0.0)
            elif float_is_zero(grade.hourly_rate, precision_digits=2):
                grade.hourly_rate = grade._formula_rate(grade._first_grade().hourly_rate)
        return grades

    def write(self, vals):
        old_rates = {grade: grade.hourly_rate for grade in self if grade.grade == 1} \
            if 'hourly_rate' in vals else {}
        res = super().write(vals)
        for grade, old_rate in old_rates.items():
            grade._fill_following_rates(old_rate)
        if 'date_to' in vals:
            self._check_no_gap_ahead()
        return res

    def _grade_label(self):
        self.ensure_one()
        return self.name or self.env._('Grade %(grade)s', grade=self.grade)

    @api.depends('name', 'grade', 'date_from', 'date_to')
    def _compute_display_name(self):
        """The period belongs in the name: a grade has one record per period.

        Without it the field on a job or a version offers several entries
        called alike, and there is no telling which period is which.
        """
        for grade in self:
            start = grade.date_from and fields.Date.to_string(grade.date_from)
            end = grade.date_to and fields.Date.to_string(grade.date_to)
            period = f'{start} – {end}' if end else f'{start} –' if start else ''
            label = grade._grade_label()
            grade.display_name = f'{label} ({period})' if period else label

    @api.model
    def _search_display_name(self, operator, value):
        # Grades are picked by their number more often than by their name.
        if operator in ('ilike', '=', '=ilike') and isinstance(value, str) \
                and value.strip().isdigit():
            return ['|', ('name', operator, value),
                    ('grade', '=', int(value.strip()))]
        return super()._search_display_name(operator, value)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_use(self):
        """A grade in use is archived, not deleted.

        Deleting it would empty the tariff grade of every job and version
        pointing at it, and payroll would quietly fall back to the salary of
        the version or of the staffing table.
        """
        Job = self.env['hr.job'].sudo().with_context(active_test=False)
        used = Job.search([('tariff_grade_id', 'in', self.ids)], limit=1)
        Version = self.env['hr.version'].sudo().with_context(active_test=False)
        if not used and 'tariff_grade_id' in Version._fields:
            used = Version.search([('tariff_grade_id', 'in', self.ids)], limit=1)
        if used:
            raise UserError(self.env._(
                'Tariff grade %(grade)s is used by job positions or employee '
                'versions. Archive it instead of deleting it.',
                grade=used.tariff_grade_id.display_name))

    def _l10n_ua_grade_on(self, on_date):
        """The grade of the same number and company in force on `on_date`.

        A version points at a grade of one period; payroll for another month
        needs the rate in force then. Periods of a grade do not overlap.
        """
        self.ensure_one()
        return self._grade_on(self.grade, on_date)

    @api.constrains('company_id', 'grade', 'date_from', 'date_to', 'active')
    def _check_period(self):
        for grade in self:
            if grade.date_to and grade.date_to < grade.date_from:
                raise ValidationError(self.env._(
                    'Tariff grade %(grade)s ends before it starts.',
                    grade=grade.name))
            domain = [
                ('id', '!=', grade.id),
                ('company_id', '=', grade.company_id.id),
                ('grade', '=', grade.grade),
                '|', ('date_to', '=', False), ('date_to', '>=', grade.date_from),
            ]
            if grade.date_to:
                domain.append(('date_from', '<=', grade.date_to))
            if grade.active and self.search_count(domain, limit=1):
                raise ValidationError(self.env._(
                    'Tariff grade %(grade)s already has a period that overlaps '
                    'the one starting on %(date)s. Close the previous period '
                    'before opening a new one.',
                    grade=grade.name, date=grade.date_from))

    @api.constrains('company_id', 'grade', 'date_from', 'date_to', 'active')
    def _check_no_gap(self):
        """A period does not start after a day with no rate in force.

        Such a day is found only when payroll stops on it, in the middle of
        the month being computed. Only the period before is looked at here:
        the history of a grade is written from the earliest period forward,
        and a period added before the ones already entered would otherwise be
        refused for a gap the next record is about to close. The gap that
        appears when a period is closed too early is checked in `write`.
        """
        for grade in self.filtered('active'):
            previous = grade._neighbour_period(before=True)
            if previous.date_to and \
                    previous.date_to + timedelta(days=1) < grade.date_from:
                raise ValidationError(grade._gap_message(previous, grade))

    def _check_no_gap_ahead(self):
        """Closing a period early leaves the same gap, seen from its own side."""
        for grade in self.filtered(lambda g: g.active and g.date_to):
            following = grade._neighbour_period(before=False)
            if following and \
                    grade.date_to + timedelta(days=1) < following.date_from:
                raise ValidationError(grade._gap_message(grade, following))

    def _neighbour_period(self, before):
        """The closest period of the same grade and company, before or after."""
        self.ensure_one()
        return self.search([
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('grade', '=', self.grade),
            ('date_from', '<' if before else '>', self.date_from),
        ], order='date_from desc' if before else 'date_from', limit=1)

    def _gap_message(self, earlier, later):
        return self.env._(
            'Tariff grade %(grade)s of %(company)s has no rate in force '
            'between %(gap_from)s and %(gap_to)s. The later period has to '
            'start on %(expected)s, otherwise payroll for that time stops.',
            grade=earlier._grade_label(), company=self.company_id.display_name,
            gap_from=earlier.date_to, gap_to=later.date_from,
            expected=earlier.date_to + timedelta(days=1))

    @api.constrains('hourly_rate', 'date_from', 'company_id')
    def _check_subsistence_minimum(self):
        """No tariff rate below the subsistence minimum on 1 January.

        Art. 6 of the Law on Remuneration of Labour. The minimum lives in the
        payroll parameters of `l10n_ua_hr_salary`; without them there is
        nothing to check against. The hourly rate is taken over the working
        hours of the month the grade starts in. A zero rate is one not entered
        yet.
        """
        if 'hr.psp.parameters' not in self.env:
            return
        for grade in self.filtered('hourly_rate'):
            year, month = grade.date_from.year, grade.date_from.month
            params = self.env['hr.psp.parameters'].sudo().get_parameters(
                Date(year, 1, 1), grade.company_id.id)
            if not params or not params.subsistence_minimum:
                continue
            weekdays = sum(
                1 for day in range(1, calendar.monthrange(year, month)[1] + 1)
                if Date(year, month, day).weekday() < 5)
            hours = weekdays * (
                grade.company_id.resource_calendar_id.hours_per_day or 8.0)
            monthly = grade.hourly_rate * hours
            if float_compare(monthly, params.subsistence_minimum,
                             precision_digits=2) < 0:
                raise ValidationError(self.env._(
                    'Tariff grade %(grade)s is %(rate).2f per hour, '
                    '%(monthly).2f a month, below the subsistence minimum for '
                    'able-bodied persons of %(minimum).2f on 1 January %(year)s '
                    '(art. 6 of the Law on Remuneration of Labour).',
                    grade=grade.name, rate=grade.hourly_rate, monthly=monthly,
                    minimum=params.subsistence_minimum, year=year))

    @api.model
    def _seed_company_grades(self, companies=None):
        """Give every company without tariff grades the typical set.

        Rates start at zero: the first-grade rate is set by each employer and
        the module cannot know it. A company that already has grades, archived
        ones included, is left alone.

        Tracking is off here: the log of a grade is about the rates its
        company agreed, and filling in the typical set is not one of them.
        """
        Grade = self.sudo().with_context(active_test=False, tracking_disable=True)
        if companies is None:
            companies = self.env['res.company'].sudo().with_context(
                active_test=False).search([])
        with_grades = {company for (company,) in Grade._read_group(
            [('company_id', 'in', companies.ids)], ['company_id'])}
        start = Date(fields.Date.context_today(self).year, 1, 1)
        templates = self.env['hr.tariff.grade.template'].sudo().search([])
        return Grade.create([
            {'company_id': company.id, 'date_from': start,
             'name': template.name, 'grade': template.grade,
             'coefficient': template.coefficient}
            for company in companies if company not in with_grades
            for template in templates
        ])


class HrTariffGradeTemplate(models.Model):
    """Typical tariff grades every company starts with.

    Loaded from data/hr_tariff_grade_data.xml: the Unified Tariff Grid (CMU
    Resolution No 1298), binding on the budget sector only. No company and no
    rate: the first-grade rate is set by each employer.
    """
    _name = 'hr.tariff.grade.template'
    _description = 'Tariff Grade Template'
    _order = 'grade'

    name = fields.Char(string='Name', required=True)
    grade = fields.Integer(string='Grade', required=True)
    coefficient = fields.Float(string='Coefficient', digits=(16, 4), default=1.0)

    _grade_uniq = models.Constraint(
        'unique(grade)',
        'Tariff grade must be unique!',
    )
