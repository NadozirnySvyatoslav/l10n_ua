import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
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
        # Працівник із валютним окладом без курсу зриває перерахунок винятком.
        # У пакеті це означало б, що через одну незаповнену дату в довіднику
        # без авансу лишається вся установа. Тому такого пропускаємо, але
        # мовчки не забуваємо: імена йдуть у повідомлення й у лог, а
        # повторний запуск (він перестворює чернетки) підхопить їх, щойно
        # курс внесуть.
        skipped = []
        for employee in employees:
            if employee.id in existing_employee_ids:
                continue
            try:
                wage = self._get_employee_wage(employee)
            except UserError:
                skipped.append(employee.name or str(employee.id))
                continue
            if not wage:
                continue
            self.env['hr.salary.advance'].create({
                'employee_id': employee.id,
                'date': self.date,
                'advance_run_id': self.id,
                'company_id': self.company_id.id,
                'wage_percent': self.wage_percent,
            })

        if skipped:
            _logger.warning(
                'Аванс %s: пропущено %s працівник(ів) без курсу валюти окладу '
                'на %s: %s', self.name, len(skipped),
                fields.Date.to_string(self.date), ', '.join(skipped))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Аванс нараховано частково'),
                    'message': _(
                        'Без авансу лишились %(count)s працівник(ів): курс '
                        'валюти їхнього окладу на %(date)s не заданий. '
                        'Внесіть курс і повторіть нарахування. %(names)s',
                        count=len(skipped),
                        date=fields.Date.to_string(self.date),
                        names=', '.join(skipped)),
                    'type': 'warning',
                    'sticky': True,
                },
            }
        return True

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

