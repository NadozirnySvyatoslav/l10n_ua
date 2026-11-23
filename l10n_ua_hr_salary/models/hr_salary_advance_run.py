import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import format_date
from dateutil.relativedelta import relativedelta
from odoo.addons.l10n_ua_account_base.tools.formatters import MONTHS_UA

_logger = logging.getLogger(__name__)



class HrSalaryAdvanceRun(models.Model):
    _name = 'hr.salary.advance.run'
    _description = 'Salary Advance Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    name = fields.Char(string='Name', required=True, tracking=True)
    date = fields.Date(string='Payment Date', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True)

    advance_ids = fields.One2many(
        'hr.salary.advance', 'advance_run_id', string='Advances')
    advance_count = fields.Integer(
        compute='_compute_advance_count')
    total_amount = fields.Monetary(
        compute='_compute_total_amount', currency_field='currency_id')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id')
    notes = fields.Text(string='Notes')
    wage_percent = fields.Float(
        string='Wage Percentage',
        default=50.0,
        tracking=True,
    )
    calculation_method = fields.Selection([
        ('percent', 'Wage Percentage'),
        ('worked_days', 'Based on Actual Days Worked'),
    ], string='Calculation Method', default='percent', required=True,
        tracking=True,
        help='Wage Percentage: the percentage of the wage. Based on Actual '
             'Days Worked: the hours of the timesheet from the 1st of the '
             'month to the payment date, at the hourly rate of the employee. '
             'The timesheet must be approved, at least partially, up to the '
             'payment date.')
    date_warning = fields.Char(compute='_compute_date_warning')

    @api.depends('date', 'company_id', 'calculation_method')
    def _compute_date_warning(self):
        for run in self:
            warnings = []
            if run.date and run.company_id:
                if run.date not in run.company_id._l10n_ua_working_dates(
                        run.date, run.date):
                    warnings.append(_(
                        'The payment date is not a working day: wages due on '
                        'a day off are paid on the working day before it.'))
                if run.calculation_method == 'worked_days' and run.date.day > 15:
                    warnings.append(_(
                        'The advance period runs from the 1st of the month to '
                        'the payment date and is longer than the first half '
                        'of the month (15 calendar days).'))
            run.date_warning = ' '.join(warnings)

    @api.depends('advance_ids')
    def _compute_advance_count(self):
        for run in self:
            run.advance_count = len(run.advance_ids)

    @api.depends('advance_ids.amount')
    def _compute_total_amount(self):
        for run in self:
            run.total_amount = sum(run.advance_ids.mapped('amount'))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.today()
        res.update({
            'date': today.replace(day=15),
            'name': 'Advance for %s %s' % (MONTHS_UA[today.month], today.year),
        })
        return res

    def write(self, vals):
        result = super().write(vals)
        if 'calculation_method' in vals:
            # The drafts are recomputed by the new method: the hours of the
            # timesheet are read only when the advances are generated.
            for run in self.filtered(lambda r: r.state == 'draft'):
                if run.advance_ids.filtered(lambda a: a.state == 'draft'):
                    run.action_generate_advances()
        if 'wage_percent' in vals:
            for run in self:
                draft_advances = run.advance_ids.filtered(lambda a: a.state == 'draft')
                if draft_advances:
                    draft_advances.write({'wage_percent': vals['wage_percent']})
        return result


    def _get_employee_wage(self, employee):
        version = employee.current_version_id
        if not version:
            return 0.0
        # Валютний оклад — у гривню за курсом на дату виплати; штатний
        # розпис уже у валюті компанії. Дата — саме дата виплати: поле на
        # версії відповідає за сьогодні, а тут питання про один конкретний
        # день, так само як і з курсом.
        #
        # Ворота `wage_from_staffing` беруться з компанії відомості. Компанія,
        # що вимкнула фолбек, нічого не отримує зі штатного розпису й у
        # листку, тож аванс проти нульового листка лише лишив би від'ємне
        # «на руки» після його ж утримання.
        return version._l10n_ua_effective_wage(
            self.date, company=self.company_id or version.company_id)

    def action_generate_advances(self):
        """Generate wage advances for all active employees."""
        self.ensure_one()
        # Delete draft advances to allow regeneration with updated percentage
        self.advance_ids.filtered(lambda a: a.state == 'draft').unlink()
        # Build lookup of employees with confirmed/paid advances to skip
        existing_employee_ids = set(self.advance_ids.mapped('employee_id').ids)
        employees = self.env['hr.employee'].search([
            ('company_id', '=', self.company_id.id),
            ('version_ids.contract_date_start', '!=', False),
        ])
        if self.calculation_method == 'worked_days':
            return self._generate_worked_days_advances(employees.filtered(
                lambda e: e.id not in existing_employee_ids))
        # Працівник із валютним окладом без курсу зриває перерахунок винятком.
        # У пакеті це означало б, що через одну незаповнену дату в довіднику
        # без авансу лишається вся установа. Тому такого пропускаємо, але
        # мовчки не забуваємо: імена йдуть у повідомлення й у лог, а
        # повторний запуск (він перестворює чернетки) підхопить їх, щойно
        # курс внесуть.
        skipped, empty = [], []
        for employee in employees:
            if employee.id in existing_employee_ids:
                continue
            try:
                wage = self._get_employee_wage(employee)
            except UserError:
                skipped.append(employee.name or str(employee.id))
                continue
            if not wage:
                empty.append(_('%(employee)s: skipped, zero wage',
                               employee=employee.name or employee.id))
                continue
            self.env['hr.salary.advance'].create({
                'employee_id': employee.id,
                'date': self.date,
                'advance_run_id': self.id,
                'company_id': self.company_id.id,
                'wage_percent': self.wage_percent,
            })

        return self._skipped_notification(skipped, empty=empty)

    def _skipped_notification(self, skipped, piece=(), empty=()):
        """The warning about the employees left without an advance, or True.

        `skipped` are those without the rate of the currency of their wage,
        `piece` those paid by piece work, whose advance is not computed from
        the hours of the timesheet, `empty` lines "employee: reason" for
        those skipped for a zero wage or month norm (#577). Everything is
        also posted to the chatter of the batch, not only shown once.
        """
        messages = []
        if skipped:
            _logger.warning(
                'Аванс %s: пропущено %s працівник(ів) без курсу валюти окладу '
                'на %s: %s', self.name, len(skipped),
                fields.Date.to_string(self.date), ', '.join(skipped))
            messages.append(_(
                'Без авансу лишились %(count)s працівник(ів): курс '
                'валюти їхнього окладу на %(date)s не заданий. '
                'Внесіть курс і повторіть нарахування. %(names)s',
                count=len(skipped),
                date=fields.Date.to_string(self.date),
                names=', '.join(skipped)))
        if piece:
            messages.append(_(
                'No advance for %(count)s piece-rate employee(s): an advance '
                'based on actual days worked is not computed for piece work. '
                '%(names)s',
                count=len(piece), names=', '.join(piece)))
        if empty:
            messages.append(_(
                'No advance for %(count)s employee(s): %(lines)s',
                count=len(empty), lines='; '.join(empty)))
        if not messages:
            return True
        self.message_post(body='\n'.join(messages))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Аванс нараховано частково'),
                'message': ' '.join(messages),
                'type': 'warning',
                'sticky': True,
            },
        }

    def _early_approved_timesheets(self):
        """Draft timesheets of the month approved up to a day before the
        payment date: the days between are not approved, and no advance for
        them can be computed."""
        self.ensure_one()
        return self.env['hr.timesheet'].search([
            ('company_id', '=', self.company_id.id),
            ('year', '=', self.date.year),
            ('month', '=', str(self.date.month)),
            ('state', '=', 'draft'),
            ('partial_approval_date', '!=', False),
            ('partial_approval_date', '<', self.date),
        ])

    def _approved_timesheet_line(self, employee):
        """The employee's timesheet line of the month approved up to the
        payment date: a confirmed or approved sheet, or one partially
        approved on or after it. The latest sheet, as the payslip reads it."""
        self.ensure_one()
        return self.env['hr.timesheet.line'].search([
            ('employee_id', '=', employee.id),
            ('timesheet_id.month', '=', str(self.date.month)),
            ('timesheet_id.year', '=', self.date.year),
            '|',
            ('timesheet_id.state', 'in', ['confirmed', 'approved']),
            ('timesheet_id.partial_approval_date', '>=', self.date),
        ], limit=1, order='timesheet_id desc')

    def _generate_worked_days_advances(self, employees):
        """Advances for the hours of the timesheet from the 1st of the month
        to the payment date.

        The hour is paid at the rate the payslip pays it at: the salary over
        the norm of the month, or the hourly rate of the tariff grade, never
        below the minimum hourly wage. Every employee must have a timesheet
        approved up to the payment date; otherwise nothing is generated, and
        the error lists every problem at once, so that the next run goes
        through for everyone.
        """
        self.ensure_one()
        if 'hr.timesheet.line' not in self.env:
            raise UserError(_(
                'An advance based on actual days worked is computed from the '
                'timesheet. Install the attendance sheet module or compute '
                'the advance as a wage percentage.'))
        company = self.company_id
        period_start = self.date.replace(day=1)
        params = self.env['hr.psp.parameters'].get_parameters(
            self.date, company.id)
        min_hourly = params.min_hourly_wage if params else 0.0

        problems = []
        early = self._early_approved_timesheets()
        for sheet in early:
            problems.append(_(
                '%(sheet)s: partially approved until %(date)s',
                sheet=sheet.display_name,
                date=format_date(self.env, sheet.partial_approval_date)))
        in_early_sheets = early.line_ids.employee_id

        skipped, piece, empty, values = [], [], [], []
        period = [period_start + relativedelta(days=n)
                  for n in range((self.date - period_start).days + 1)]
        for employee in employees:
            if not any(employee._l10n_ua_employed_on(day) for day in period):
                continue
            version = employee._l10n_ua_version_on(self.date) \
                or employee.current_version_id
            if not version:
                continue
            salary_form = version.salary_form or 'salary'
            if salary_form == 'piece':
                piece.append(employee.name or str(employee.id))
                continue
            norm_hours = employee._l10n_ua_month_norm(
                company, self.date, version)[1]
            if salary_form == 'hourly':
                grade = version.tariff_grade_id._l10n_ua_grade_on(self.date) \
                    if version.tariff_grade_id else version.tariff_grade_id
                if not grade.hourly_rate:
                    problems.append(_(
                        '%(employee)s: tariff grade %(grade)s has no hourly '
                        'rate in force on %(date)s',
                        employee=employee.name,
                        grade=version.tariff_grade_id.display_name or '-',
                        date=format_date(self.env, self.date)))
                    continue
                hourly_rate = max(grade.hourly_rate, min_hourly)
            else:
                try:
                    wage = version._l10n_ua_effective_wage(
                        self.date, company=company or version.company_id)
                except UserError:
                    skipped.append(employee.name or str(employee.id))
                    continue
                if not wage or norm_hours <= 0:
                    empty.append(_(
                        '%(employee)s: skipped, zero wage',
                        employee=employee.name or employee.id) if not wage
                        else _('%(employee)s: skipped, no month norm of '
                               'hours', employee=employee.name or employee.id))
                    continue
                hourly_rate = wage / norm_hours
            line = self._approved_timesheet_line(employee)
            if not line:
                if employee not in in_early_sheets:
                    problems.append(_(
                        '%(employee)s (%(department)s): no timesheet approved '
                        'up to the payment date',
                        employee=employee.name,
                        department=employee.department_id.name or '-'))
                continue
            worked_hours = sum(line.day_ids.filtered(
                lambda d: d.date and period_start <= d.date <= self.date
            ).mapped('hours'))
            if worked_hours <= 0:
                continue
            values.append({
                'employee_id': employee.id,
                'date': self.date,
                'advance_run_id': self.id,
                'company_id': company.id,
                'calculation_method': 'worked_days',
                'wage_percent': self.wage_percent,
                'worked_hours': worked_hours,
                'norm_hours': norm_hours,
                'hourly_rate': hourly_rate,
            })

        if problems:
            raise UserError(_(
                'The advances cannot be computed for %(date)s: the timesheet '
                'of every employee must be approved, at least partially, up '
                'to the payment date. Fix the following and generate the '
                'advances again:\n%(problems)s',
                date=format_date(self.env, self.date),
                problems='\n'.join('- ' + problem for problem in problems)))
        self.env['hr.salary.advance'].create(values)
        return self._skipped_notification(skipped, piece, empty)

    def action_confirm_all(self):
        self.ensure_one()
        self.advance_ids.filtered(lambda a: a.state == 'draft').action_confirm()
        self.write({'state': 'confirmed'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_draft(self):
        self.advance_ids.filtered(lambda a: a.state == 'confirmed').action_draft()
        self.write({'state': 'draft'})

    def action_open_advances(self):
        return {
            'name': _('Advances'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.salary.advance',
            'view_mode': 'list,form',
            'domain': [('advance_run_id', '=', self.id)],
            'context': {'default_advance_run_id': self.id, 'default_date': self.date},
        }

