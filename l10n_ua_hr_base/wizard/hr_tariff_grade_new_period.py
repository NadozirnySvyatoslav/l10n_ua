from dateutil.relativedelta import relativedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class HrTariffGradeNewPeriod(models.TransientModel):
    """Close the tariff grades of a company and open them anew from a date.

    Doing it by hand means two operations per grade, and the order matters:
    a period that is not closed first blocks the new one, and a period closed
    too early leaves a month with no rate in force, which stops payroll. The
    wizard closes and opens in one transaction, so neither can happen.
    """
    _name = 'hr.tariff.grade.new.period'
    _description = 'New Tariff Rates from Date'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date_from = fields.Date(
        string='Rates Valid From', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1)
        + relativedelta(months=1),
        help='The grades in force are closed the day before this date.')
    base_rate = fields.Monetary(
        string='First Grade Hourly Rate', currency_field='currency_id',
        compute='_compute_base_rate', store=True, readonly=False,
        help='New hourly rate of grade 1. The grades that followed the '
             'formula are recomputed from it.')
    line_ids = fields.One2many(
        'hr.tariff.grade.new.period.line', 'wizard_id', string='Grades',
        compute='_compute_line_ids', store=True, readonly=False)

    def _current_grades(self):
        self.ensure_one()
        if not (self.company_id and self.date_from):
            return self.env['hr.tariff.grade']
        return self.env['hr.tariff.grade'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '<', self.date_from),
            '|', ('date_to', '=', False),
            ('date_to', '>=', self.date_from - relativedelta(days=1)),
        ], order='grade')

    @api.depends('company_id', 'date_from')
    def _compute_base_rate(self):
        for wizard in self:
            first = wizard._current_grades().filtered(lambda g: g.grade == 1)
            wizard.base_rate = first.hourly_rate

    @api.depends('company_id', 'date_from', 'base_rate')
    def _compute_line_ids(self):
        for wizard in self:
            grades = wizard._current_grades()
            wizard.line_ids = [Command.clear()] + [
                Command.create({
                    'grade_id': grade.id,
                    'new_rate': wizard._new_rate(grade),
                    'rate_source': wizard._rate_source(grade),
                })
                for grade in grades
            ]

    def _rate_source(self, grade):
        """Where the new rate of this grade comes from.

        A rate that differs from the first-grade rate × coefficient was
        agreed apart from the formula — in the collective agreement it is a
        number of its own — so raising the first-grade rate does not move it.
        """
        self.ensure_one()
        if grade.grade == 1:
            return 'base'
        if float_is_zero(grade.hourly_rate, precision_digits=2):
            return 'formula'
        return 'formula' if float_is_zero(grade.rate_diff, precision_digits=2) \
            else 'agreed'

    def _new_rate(self, grade):
        """The rate the grade gets, according to where it comes from."""
        self.ensure_one()
        source = self._rate_source(grade)
        if source == 'base':
            return self.base_rate
        if source == 'agreed':
            return grade.hourly_rate
        currency = self.currency_id
        amount = self.base_rate * grade.coefficient
        return currency.round(amount) if currency else round(amount, 2)

    def action_apply(self):
        self.ensure_one()
        grades = self._current_grades()
        if not grades:
            raise UserError(self.env._(
                'Company "%(company)s" has no tariff grades in force before '
                '%(date)s. Enter the grades first.',
                company=self.company_id.display_name, date=self.date_from))
        # Any grade already reaching into the new period is a sign that the
        # rates were changed by hand: the wizard would rather say so than
        # build a second, conflicting set beside it. Archived grades are out
        # of the way and do not count.
        later = self.env['hr.tariff.grade'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', self.date_from),
        ], limit=1)
        if later:
            raise UserError(self.env._(
                'Company "%(company)s" already has a period of tariff grade '
                '%(grade)s starting on %(date)s. Close or remove it before '
                'opening the new rates.',
                grade=later.display_name, company=self.company_id.display_name,
                date=later.date_from))

        # Closing comes first: a period still open would overlap the new one.
        last_day = self.date_from - relativedelta(days=1)
        for grade in grades:
            if not grade.date_to or grade.date_to > last_day:
                grade.date_to = last_day
        new_grades = self.env['hr.tariff.grade']
        for line in self.line_ids.sorted(lambda l: l.grade):
            grade = line.grade_id
            new_grades |= grade.copy({
                'date_from': self.date_from,
                'date_to': False,
                'hourly_rate': line.new_rate,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Tariff Grades'),
            'res_model': 'hr.tariff.grade',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_grades.ids)],
        }


class HrTariffGradeNewPeriodLine(models.TransientModel):
    _name = 'hr.tariff.grade.new.period.line'
    _description = 'New Tariff Rates from Date Line'
    _order = 'grade'

    wizard_id = fields.Many2one(
        'hr.tariff.grade.new.period', required=True, ondelete='cascade')
    grade_id = fields.Many2one(
        'hr.tariff.grade', string='Tariff Grade', required=True,
        ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    name = fields.Char(related='grade_id.name', string='Name')
    grade = fields.Integer(related='grade_id.grade', string='Grade')
    coefficient = fields.Float(related='grade_id.coefficient', string='Coefficient')
    current_rate = fields.Monetary(
        related='grade_id.hourly_rate', string='Current Rate',
        currency_field='currency_id')
    new_rate = fields.Monetary(
        string='New Rate', currency_field='currency_id',
        help='Filled in from the first-grade rate and the coefficient where '
             'the current rate followed that formula, and kept as it is where '
             'it was agreed otherwise.')
    rate_diff = fields.Monetary(
        string='Change', compute='_compute_rate_diff',
        currency_field='currency_id')
    rate_source = fields.Selection(
        [('base', 'First-grade rate'),
         ('formula', 'First-grade rate × coefficient'),
         ('agreed', 'Agreed apart from the formula')],
        string='New Rate From', readonly=True,
        help='Where the new rate comes from. A rate agreed apart from the '
             'formula keeps its value when the first-grade rate changes, '
             'because in the collective agreement it is a number of its own. '
             'Correct it by hand if it has to change too.')

    @api.depends('new_rate', 'current_rate')
    def _compute_rate_diff(self):
        for line in self:
            line.rate_diff = round(line.new_rate - line.current_rate, 2)

    @api.constrains('new_rate')
    def _check_new_rate(self):
        for line in self:
            if float_compare(line.new_rate, 0.0, precision_digits=2) < 0:
                raise UserError(self.env._('A tariff rate cannot be negative.'))
