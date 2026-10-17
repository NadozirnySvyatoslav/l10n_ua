"""Schemes of salaries in coefficients of a base value.

CMU Resolution No 1078 of 31.08.2026 takes the pedagogical and academic staff
of state and communal education out of the Unified Tariff Grid (Resolution
No 1298): from 1 September 2026 their salary is the base value (28 885 UAH)
times the coefficient of the position. The grid stays where it was — for the
rest of the budget sector and for local-budget institutions that have not
moved yet — so the two live side by side, and a position is paid by the
scheme only from the day the scheme applies.

The base value is a dated parameter, not a constant: the act states it per
date, and the next one will state another. A salary is always read for a date.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round


class HrPayBaseValue(models.Model):
    """Базова величина для визначення посадових окладів, на період."""
    _name = 'hr.pay.base.value'
    _description = 'Pay Base Value'
    _order = 'date_from desc'
    _rec_name = 'date_from'

    date_from = fields.Date(string='Valid From', required=True)
    amount = fields.Monetary(
        string='Base Value', currency_field='currency_id', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self.env.ref('base.UAH', raise_if_not_found=False))
    legal_basis = fields.Char(string='Legal Basis')
    active = fields.Boolean(default=True)

    _date_from_active_uniq = models.UniqueIndex(
        '(date_from) WHERE active',
        'There is already a base value starting on this date.',
    )

    @api.constrains('amount')
    def _check_amount(self):
        for value in self:
            if value.amount <= 0:
                raise ValidationError(self.env._(
                    'The base value from %(date)s must be positive.',
                    date=value.date_from))

    @api.depends('date_from', 'amount')
    def _compute_display_name(self):
        for value in self:
            value.display_name = f'{value.amount:.2f} ({value.date_from})' \
                if value.date_from else ''

    @api.model
    def _value_on(self, on_date):
        """The base value in force on `on_date`, or an empty record."""
        if not on_date:
            return self.browse()
        return self.sudo().search(
            [('date_from', '<=', on_date)], order='date_from desc', limit=1)


class HrPayScheme(models.Model):
    """A scheme of salaries (or hourly rates) in coefficients."""
    _name = 'hr.pay.scheme'
    _description = 'Pay Scheme'
    _order = 'date_from desc, sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('salary', 'Monthly Salaries'),
        ('hourly', 'Hourly Rates'),
    ], string='Kind', required=True, default='salary',
        help='Monthly salaries: base value × coefficient is the salary of a '
             'position. Hourly rates: base value × coefficient is the rate of '
             'one hour of teaching.')
    date_from = fields.Date(
        string='Applies From', required=True,
        help='No position is paid by this scheme for a period before this '
             'date: until then the Unified Tariff Grid applies.')
    legal_basis = fields.Char(string='Legal Basis')
    line_ids = fields.One2many('hr.pay.scheme.line', 'scheme_id', string='Positions')
    active = fields.Boolean(default=True)


class HrPaySchemeLine(models.Model):
    """One position (or category of a position) of a scheme."""
    _name = 'hr.pay.scheme.line'
    _description = 'Pay Scheme Position'
    _order = 'scheme_id, sequence, id'

    scheme_id = fields.Many2one(
        'hr.pay.scheme', string='Scheme', required=True, ondelete='cascade',
        index=True)
    sequence = fields.Integer(default=10)
    group_name = fields.Char(
        string='Position Group',
        help='The heading of the scheme the line stands under, when the '
             'coefficient depends on a category, a size of the institution or '
             'a length of service.')
    name = fields.Char(string='Position', required=True)
    coefficient = fields.Float(
        string='Coefficient', digits=(16, 4), required=True,
        help='Multiplier of the base value. A rate the act gives in per cent '
             'of the base value is kept as a fraction: 1.2 % is 0.012.')
    kind = fields.Selection(related='scheme_id.kind', store=True)
    date_from = fields.Date(related='scheme_id.date_from', store=True)
    amount = fields.Monetary(
        string='Amount', compute='_compute_amount',
        currency_field='currency_id',
        help='Base value in force today (or on the start of a scheme that '
             'applies later) × coefficient, rounded to a whole hryvnia.')
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_amount')
    active = fields.Boolean(default=True)

    @api.depends('coefficient', 'scheme_id.date_from')
    def _compute_amount(self):
        today = fields.Date.context_today(self)
        for line in self:
            # A scheme that applies later is shown at its own start.
            on_date = max(today, line.date_from) if line.date_from else today
            value = self.env['hr.pay.base.value']._value_on(on_date)
            line.currency_id = value.currency_id
            line.amount = line._amount_from(value) if value else 0.0

    @api.depends('name', 'group_name', 'coefficient')
    def _compute_display_name(self):
        for line in self:
            label = f'{line.group_name} — {line.name}' if line.group_name \
                else line.name or ''
            line.display_name = f'{label} ({line.coefficient:g})'

    def _amount_from(self, base_value):
        """Base value × coefficient, to a whole hryvnia.

        The notes to the schemes: below 0.5 is dropped, 0.5 and above is
        rounded up to one hryvnia — half up, not the banker's rounding.
        """
        self.ensure_one()
        return float_round(base_value.amount * self.coefficient,
                           precision_digits=0, rounding_method='HALF-UP')

    def _amount_on(self, on_date):
        """The salary (or the hourly rate) of this position on `on_date`.

        Refuses a date before the scheme applies, and a date with no base
        value in force: both would otherwise pay a figure from another period,
        or none, without a word.
        """
        self.ensure_one()
        self._check_applies_on(on_date)
        value = self.env['hr.pay.base.value']._value_on(on_date)
        if not value:
            raise ValidationError(self.env._(
                'No base value is in force on %(date)s. Enter it in Base '
                'Values before using the scheme %(scheme)s.',
                date=on_date, scheme=self.scheme_id.name))
        return self._amount_from(value)

    def _check_applies_on(self, on_date, what=None):
        self.ensure_one()
        if on_date and self.date_from and on_date < self.date_from:
            raise ValidationError(self.env._(
                '%(what)s starts on %(date)s, before the scheme %(scheme)s '
                'applies (%(start)s). For that period the Unified Tariff Grid '
                'applies: open a new period from %(start)s for the scheme.',
                what=what or self.display_name, date=on_date,
                scheme=self.scheme_id.name, start=self.date_from))


class HrStaffingTable(models.Model):
    _inherit = 'hr.staffing.table'

    pay_scheme_line_id = fields.Many2one(
        'hr.pay.scheme.line', string='Salary Scheme Position',
        domain=[('kind', '=', 'salary')], tracking=True,
        help='The position in a scheme of salaries in coefficients (CMU '
             'Resolution No 1078). The salary of the line is filled with the '
             'base value in force on its start date × the coefficient. A line '
             'before the scheme applies keeps the tariff-grid salary.')
    pay_scheme_salary = fields.Monetary(
        string='Scheme Salary', currency_field='currency_id',
        compute='_compute_pay_scheme_salary',
        help='Base value in force on the start date × coefficient.')

    @api.depends('pay_scheme_line_id', 'date_from')
    def _compute_pay_scheme_salary(self):
        Base = self.env['hr.pay.base.value']
        for line in self:
            scheme = line.pay_scheme_line_id
            value = Base._value_on(line.date_from) if scheme else Base
            ok = value and not (scheme.date_from and line.date_from
                                and line.date_from < scheme.date_from)
            line.pay_scheme_salary = scheme._amount_from(value) if ok else 0.0

    @api.onchange('pay_scheme_line_id', 'date_from')
    def _onchange_pay_scheme_line_id(self):
        if self.pay_scheme_line_id and self.pay_scheme_salary:
            self.salary = self.pay_scheme_salary

    @api.model
    def _fill_scheme_salary(self, vals, scheme_line, date_from):
        if scheme_line and 'salary' not in vals:
            vals['salary'] = scheme_line._amount_on(date_from)

    @api.model_create_multi
    def create(self, vals_list):
        SchemeLine = self.env['hr.pay.scheme.line']
        for vals in vals_list:
            if vals.get('pay_scheme_line_id'):
                self._fill_scheme_salary(
                    vals, SchemeLine.browse(vals['pay_scheme_line_id']),
                    fields.Date.to_date(vals.get('date_from'))
                    or fields.Date.context_today(self))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('pay_scheme_line_id') and 'salary' not in vals:
            scheme_line = self.env['hr.pay.scheme.line'].browse(
                vals['pay_scheme_line_id'])
            for line in self:
                line_vals = dict(vals)
                self._fill_scheme_salary(
                    line_vals, scheme_line,
                    fields.Date.to_date(vals.get('date_from')) or line.date_from)
                super(HrStaffingTable, line).write(line_vals)
            return True
        return super().write(vals)

    @api.constrains('pay_scheme_line_id', 'date_from')
    def _check_pay_scheme_period(self):
        for line in self.filtered('pay_scheme_line_id'):
            line.pay_scheme_line_id._check_applies_on(
                line.date_from, what=line.display_name)


class HrVersion(models.Model):
    _inherit = 'hr.version'

    pay_scheme_line_id = fields.Many2one(
        'hr.pay.scheme.line', string='Salary Scheme Position',
        domain=[('kind', '=', 'salary')], tracking=True,
        groups='hr.group_hr_manager',
        help='The position in a scheme of salaries in coefficients (CMU '
             'Resolution No 1078): the wage of this version is filled with '
             'the base value in force on the version date × the coefficient. '
             'A version dated before the scheme applies keeps the tariff-grid '
             'wage.')
    pay_scheme_salary = fields.Monetary(
        string='Scheme Salary', currency_field='currency_id',
        compute='_compute_pay_scheme_salary', groups='hr.group_hr_manager',
        help='Base value in force on the version date × coefficient.')

    @api.depends('pay_scheme_line_id', 'date_version')
    def _compute_pay_scheme_salary(self):
        Base = self.env['hr.pay.base.value']
        for version in self:
            scheme = version.pay_scheme_line_id
            value = Base._value_on(version.date_version) if scheme else Base
            ok = value and not (scheme.date_from and version.date_version
                                and version.date_version < scheme.date_from)
            version.pay_scheme_salary = scheme._amount_from(value) if ok else 0.0

    @api.onchange('pay_scheme_line_id', 'date_version')
    def _onchange_pay_scheme_line_id(self):
        if self.pay_scheme_line_id and self.pay_scheme_salary:
            self.wage = self.pay_scheme_salary

    @api.model_create_multi
    def create(self, vals_list):
        SchemeLine = self.env['hr.pay.scheme.line']
        for vals in vals_list:
            if vals.get('pay_scheme_line_id') and 'wage' not in vals:
                vals['wage'] = SchemeLine.browse(
                    vals['pay_scheme_line_id'])._amount_on(
                        fields.Date.to_date(vals.get('date_version'))
                        or fields.Date.context_today(self))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('pay_scheme_line_id') and 'wage' not in vals:
            scheme_line = self.env['hr.pay.scheme.line'].browse(
                vals['pay_scheme_line_id'])
            for version in self:
                on_date = fields.Date.to_date(vals.get('date_version')) \
                    or version.date_version
                super(HrVersion, version).write(
                    dict(vals, wage=scheme_line._amount_on(on_date)))
            return True
        return super().write(vals)

    @api.constrains('pay_scheme_line_id', 'date_version')
    def _check_pay_scheme_period(self):
        for version in self.filtered('pay_scheme_line_id'):
            version.pay_scheme_line_id._check_applies_on(
                version.date_version,
                what=self.env._('The version of %(employee)s',
                                employee=version.employee_id.name or ''))


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    pay_scheme_line_id = fields.Many2one(
        related='version_id.pay_scheme_line_id', inherited=True,
        readonly=False, groups='hr.group_hr_manager')
    pay_scheme_salary = fields.Monetary(
        related='version_id.pay_scheme_salary', inherited=True,
        groups='hr.group_hr_manager')

    @api.onchange('pay_scheme_line_id', 'date_version')
    def _onchange_pay_scheme_line_id(self):
        if self.pay_scheme_line_id and self.pay_scheme_salary:
            self.wage = self.pay_scheme_salary
