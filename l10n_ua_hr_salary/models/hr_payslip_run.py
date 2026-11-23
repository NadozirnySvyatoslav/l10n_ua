import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class HrPayslipRun(models.Model):
    _name = 'hr.payslip.run'
    _description = 'Payslip Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc'

    name = fields.Char(
        string='Name',
        required=True,
        tracking=True
    )
    date_start = fields.Date(
        string='Date From',
        required=True,
        tracking=True
    )
    date_end = fields.Date(
        string='Date To',
        required=True,
        tracking=True
    )
    
    slip_ids = fields.One2many(
        'hr.payslip',
        'payslip_run_id',
        string='Payslips'
    )
    payslip_count = fields.Integer(
        string='Payslip Count',
        compute='_compute_payslip_count'
    )
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verify', 'Verify'),
        ('close', 'Done'),
    ], string='Status', default='draft', tracking=True)
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    
    total_gross = fields.Monetary(
        string='Total Gross',
        compute='_compute_totals',
        currency_field='currency_id'
    )
    total_net = fields.Monetary(
        string='Total Net',
        compute='_compute_totals',
        currency_field='currency_id'
    )
    total_pdfo = fields.Monetary(
        string='Total PDFO',
        compute='_compute_totals',
        currency_field='currency_id'
    )
    total_military = fields.Monetary(
        string='Total Military Tax',
        compute='_compute_totals',
        currency_field='currency_id'
    )
    total_esv = fields.Monetary(
        string='Total ESV',
        compute='_compute_totals',
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id'
    )
    
    notes = fields.Text(string='Notes')

    def _compute_payslip_count(self):
        for run in self:
            run.payslip_count = len(run.slip_ids)

    @api.depends('slip_ids.gross_salary', 'slip_ids.net_salary', 
                 'slip_ids.pdfo_amount', 'slip_ids.military_tax_amount',
                 'slip_ids.esv_amount')
    def _compute_totals(self):
        for run in self:
            run.total_gross = sum(run.slip_ids.mapped('gross_salary'))
            run.total_net = sum(run.slip_ids.mapped('net_salary'))
            run.total_pdfo = sum(run.slip_ids.mapped('pdfo_amount'))
            run.total_military = sum(run.slip_ids.mapped('military_tax_amount'))
            run.total_esv = sum(run.slip_ids.mapped('esv_amount'))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.today()
        first_day = today.replace(day=1)
        last_day = (first_day + relativedelta(months=1, days=-1))
        
        res.update({
            'date_start': first_day,
            'date_end': last_day,
            'name': f'Зарплата за {today.strftime("%B %Y")}',
        })
        return res

    def action_generate_payslips(self):
        """Generate payslips for all employees with active contracts"""
        self.ensure_one()
        
        # Find employees with active versions (contract_date_start set, no end date)
        employees = self.env['hr.employee'].search([
            ('company_id', '=', self.company_id.id),
            ('version_ids.contract_date_start', '!=', False),
        ])
        
        # Кожен працівник у власному savepoint (#577): одна помилка (напр.
        # валютний оклад без курсу на дату) раніше відкочувала весь пакет, і
        # бухгалтер не отримував жодного листка. Тепер листки, що
        # порахувались, лишаються, а проблемні йдуть у чаттер пакета й у
        # сповіщення; повторний запуск підхопить їх без дублів.
        failed = []
        for employee in employees:
            existing = self.slip_ids.filtered(lambda s: s.employee_id == employee)
            if existing:
                continue
            try:
                with self.env.cr.savepoint():
                    payslip = self.env['hr.payslip'].create({
                        'employee_id': employee.id,
                        'payslip_run_id': self.id,
                        'date_from': self.date_start,
                        'date_to': self.date_end,
                        'company_id': self.company_id.id,
                    })
                    payslip.action_compute_sheet()
            except UserError as error:
                self.env.invalidate_all()
                failed.append('%s: %s' % (
                    employee.name or employee.id,
                    error.args[0] if error.args else error))

        return self._failed_notification(failed)

    def _failed_notification(self, failed):
        """Post the employees left without a payslip and warn the user."""
        if not failed:
            return True
        _logger.warning('Пакет %s: без листка %s працівник(ів): %s',
                        self.name, len(failed), '; '.join(failed))
        body = _('No payslip for %(count)s employee(s), fix and generate '
                 'again:\n%(lines)s', count=len(failed),
                 lines='\n'.join('- ' + line for line in failed))
        self.message_post(body=body)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payslips generated partially'),
                'message': body,
                'type': 'warning',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_compute_all(self):
        """Compute all payslips in batch"""
        for slip in self.slip_ids:
            slip.action_compute_sheet()
        return True

    def action_verify(self):
        self.slip_ids.filtered(lambda s: s.state == 'draft').write({'state': 'verify'})
        self.write({'state': 'verify'})

    def action_close(self):
        self.slip_ids.filtered(lambda s: s.state == 'verify').write({'state': 'done'})
        self.write({'state': 'close'})

    def action_draft(self):
        self.slip_ids.write({'state': 'draft'})
        self.write({'state': 'draft'})

    def action_bank_export(self):
        """Відкрити майстер формування зарплатного файлу для клієнт-банку (#152)."""
        self.ensure_one()
        return {
            'name': _('Зарплатний файл у банк'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip.bank.export',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payslip_run_id': self.id},
        }

    def action_open_payslips(self):
        return {
            'name': 'Payslips',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('payslip_run_id', '=', self.id)],
            'context': {
                'default_payslip_run_id': self.id,
                'default_date_from': self.date_start,
                'default_date_to': self.date_end,
            },
        }
