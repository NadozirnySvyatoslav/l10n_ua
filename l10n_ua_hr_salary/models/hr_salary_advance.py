from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrSalaryAdvance(models.Model):
    _name = 'hr.salary.advance'
    _description = 'Salary Advance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False,
        readonly=True, default=lambda self: _('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        tracking=True, index=True,
    )
    date = fields.Date(
        string='Payment Date', required=True,
        default=fields.Date.context_today, tracking=True,
    )
    wage_percent = fields.Float(
        string='Wage Percentage', 
        default=50.0, 
        tracking=True,
    )
    gross_amount = fields.Monetary(
        string='Gross',
        compute='_compute_gross_amount', store=True,
        currency_field='currency_id',
    )
    pdfo_rate = fields.Float(string='PDFO (%)', default=18.0)
    pdfo_amount = fields.Monetary(
        string='PDFO',
        compute='_compute_taxes', store=True,
        currency_field='currency_id',
    )
    military_rate = fields.Float(string='Military Tax (%)', default=5.0)
    military_amount = fields.Monetary(
        string='Military Tax',
        compute='_compute_taxes', store=True,
        currency_field='currency_id',
    )
    amount = fields.Monetary(
        string='Net Advance',
        compute='_compute_taxes', store=True, tracking=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
    ], string='Status', default='draft', required=True,
        tracking=True, index=True,
    )
    notes = fields.Text(string='Notes')
    advance_run_id = fields.Many2one(
        'hr.salary.advance.run', string='Advance Batch',
        readonly=True, copy=False, ondelete='set null',
    )
    payslip_id = fields.Many2one(
        'hr.payslip', string='Payslip', readonly=True, copy=False,
        help='Payslip from which this advance was deducted',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    department_id = fields.Many2one(
        'hr.department', related='employee_id.department_id',
        store=True, readonly=True,
    )

    # `staffing_line_id.salary` is no longer a dependency: the field is
    # computed and not stored, so the ORM has no column to walk the path back
    # through. The fallback in the method body stays; only the moment of
    # recomputation changes - draft advances are refreshed when the run
    # regenerates them, and confirmed ones must not change retroactively.
    @api.depends(
        'employee_id', 'wage_percent', 'date',
        'employee_id.current_version_id.wage',
        'employee_id.current_version_id.salary_currency_id',
    )
    def _compute_gross_amount(self):
        for advance in self:
            wage = 0.0
            if advance.employee_id:
                version = advance.employee_id.current_version_id
                if version:
                    # Курс — на дату виплати авансу: аванс середини місяця й
                    # зарплата в кінці рахуються кожне за своїм.
                    wage = version._l10n_ua_wage_in_company_currency(advance.date)
                    # Same gate as the payslip (`_get_effective_wage`). Where
                    # a company has turned the fallback off, the payslip
                    # calculates zero; paying an advance from the staffing
                    # table anyway would leave that payslip deducting an
                    # advance it never earned.
                    setting = (advance.company_id
                               or version.company_id).wage_from_staffing
                    if not wage and (setting or 'both') in ('fallback', 'both'):
                        # The staffing table is asked about the payment
                        # date too, not read off the version, which answers
                        # for today. It is kept in the company currency, so
                        # there is nothing to convert here.
                        staffing = self.env['hr.staffing.table'].with_company(
                            version.company_id)._resolve(
                                version.company_id, version.department_id,
                                version.job_id, advance.date)
                        wage = staffing.salary or 0.0
            advance.gross_amount = round(wage * advance.wage_percent / 100, 2)

    @api.depends(
        'gross_amount', 'pdfo_rate', 'military_rate',
        'employee_id.current_version_id.contract_type_ua',
        'employee_id.current_version_id.diia_city_employee',
    )
    def _compute_taxes(self):
        for advance in self:
            pdfo_rate = advance.pdfo_rate
            military_rate = advance.military_rate

            if advance.employee_id:
                version = advance.employee_id.current_version_id
                if version:
                    is_gig = (
                        version.contract_type_ua == 'gig'
                        or version.diia_city_employee
                    )
                    if is_gig:
                        pdfo_rate = 5.0
                        military_rate = 0.0

            pdfo = round(advance.gross_amount * pdfo_rate / 100, 2)
            military = round(advance.gross_amount * military_rate / 100, 2)
            advance.pdfo_amount = pdfo
            advance.military_amount = military
            advance.amount = advance.gross_amount - pdfo - military

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.salary.advance') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        for advance in self:
            if advance.state != 'draft':
                raise UserError(_('Only draft advances can be confirmed.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        for advance in self:
            if advance.state == 'paid':
                raise UserError(_('Paid advances cannot be reset to draft.'))
        self.write({'state': 'draft', 'payslip_id': False})

    def unlink(self):
        for advance in self:
            if advance.state == 'paid':
                raise UserError(_('Cannot delete paid advances.'))
        return super().unlink()

