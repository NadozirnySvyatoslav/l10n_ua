"""Ukrainian Advance Report (Авансовий звіт) model."""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AdvanceReport(models.Model):
    """Advance Report (Авансовий звіт).

    A document used to account for money given to an employee in advance
    for business expenses (travel, purchases, etc.).
    """
    _name = 'l10n_ua.advance.report'
    _description = 'Advance Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Number',
        required=True,
        copy=False,
        readonly=True,
        default='/',
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    # Purpose
    purpose = fields.Char(
        string='Purpose',
        required=True,
        help='Purpose of the advance (business trip, purchase, etc.)',
    )

    # Advance details
    advance_date = fields.Date(
        string='Advance Date',
        help='Date when advance was given to employee',
    )
    advance_amount = fields.Monetary(
        string='Advance Received',
        currency_field='currency_id',
        help='Amount received by employee',
    )

    # Previous balance
    previous_balance = fields.Monetary(
        string='Previous Balance',
        currency_field='currency_id',
        help='Balance from previous advance report',
    )

    # Expense lines
    line_ids = fields.One2many(
        'l10n_ua.advance.report.line',
        'report_id',
        string='Expense Lines',
    )

    # Computed amounts
    total_expenses = fields.Monetary(
        string='Total Expenses',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    balance = fields.Monetary(
        string='Balance',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
        help='Positive = employee owes, Negative = company owes',
    )

    # State
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )

    # Related move
    move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False,
    )

    # Approval
    approved_by = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
    )
    approved_date = fields.Datetime(
        string='Approved Date',
        readonly=True,
    )

    # Notes
    note = fields.Text(string='Notes')

    @api.depends('line_ids.amount', 'advance_amount', 'previous_balance')
    def _compute_amounts(self):
        for report in self:
            report.total_expenses = sum(report.line_ids.mapped('amount'))
            # Balance = what was given - what was spent
            # Positive = employee should return
            # Negative = company should pay more
            report.balance = (
                (report.advance_amount or 0.0)
                + (report.previous_balance or 0.0)
                - report.total_expenses
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.advance.report'
                ) or '/'
        return super().create(vals_list)

    def action_submit(self):
        """Submit report for approval."""
        for report in self:
            if report.state != 'draft':
                raise UserError(_('Only draft reports can be submitted.'))
            if not report.line_ids:
                raise UserError(_('Cannot submit a report without expense lines.'))
            report.state = 'submitted'

    def action_approve(self):
        """Approve the report."""
        for report in self:
            if report.state != 'submitted':
                raise UserError(_('Only submitted reports can be approved.'))
            report.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })

    def _get_advance_journal(self):
        """Journal for the advance-report entry (company setting or first general)."""
        self.ensure_one()
        journal = self.company_id.l10n_ua_advance_journal_id
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'general'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not journal:
            raise UserError(_(
                'No journal for advance reports. Configure a general journal '
                'for company "%s".', self.company_id.display_name))
        return journal

    def _get_settlement_account(self):
        """Accountable-persons settlement account (372) — credited on posting."""
        self.ensure_one()
        account = self.company_id.l10n_ua_advance_account_id
        if not account:
            account = self.env['account.account'].search([
                ('code', '=like', '372%'),
                ('company_ids', 'in', self.company_id.id),
            ], limit=1)
        if not account:
            raise UserError(_(
                'No accountable-persons settlement account (372) found. '
                'Configure it in the company settings (Ukrainian accounting).'))
        return account

    def _prepare_move_lines(self):
        """Build balanced entry: Дт expense accounts — Кт 372 (settlements)."""
        self.ensure_one()
        default_expense = self.company_id.l10n_ua_advance_expense_account_id
        move_lines = []
        for line in self.line_ids:
            account = line.account_id or default_expense
            if not account:
                raise UserError(_(
                    'Set an expense account on line "%s" (or a default expense '
                    'account in the company settings) before posting.',
                    line.description or line.expense_type))
            move_lines.append((0, 0, {
                'name': line.description or self.purpose,
                'account_id': account.id,
                'partner_id': line.partner_id.id or False,
                'debit': line.amount,
                'credit': 0.0,
            }))
        settlement = self._get_settlement_account()
        # #722: read the contact via the public profile. Reading it on
        # hr.employee prefetches private fields (l10n_ua_hr_base) and raises
        # AccessError for an accountant without HR rights.
        employee_partner = self.env['hr.employee.public'].browse(
            self.employee_id.id).work_contact_id
        move_lines.append((0, 0, {
            'name': _('Advance report %s', self.name),
            'account_id': settlement.id,
            'partner_id': employee_partner.id or False,
            'debit': 0.0,
            'credit': self.total_expenses,
        }))
        return move_lines

    def action_post(self):
        """Post the report and create the balanced journal entry (Дт витрати — Кт 372)."""
        for report in self:
            if report.state != 'approved':
                raise UserError(_('Only approved reports can be posted.'))
            if not report.line_ids:
                raise UserError(_('Cannot post a report without expense lines.'))
            if report.move_id:
                raise UserError(_('This report already has a journal entry.'))
            if report.currency_id.is_zero(report.total_expenses):
                raise UserError(_('Cannot post a report with zero total expenses.'))

            move = self.env['account.move'].create({
                'move_type': 'entry',
                'journal_id': report._get_advance_journal().id,
                'date': report.date,
                'ref': _('Advance report %s', report.name),
                'company_id': report.company_id.id,
                'line_ids': report._prepare_move_lines(),
            })
            move.action_post()
            report.move_id = move.id
            report.state = 'posted'

    def action_draft(self):
        """Reset to draft state."""
        for report in self:
            if report.state == 'posted':
                raise UserError(_('Cannot reset a posted report to draft.'))
            report.write({
                'state': 'draft',
                'approved_by': False,
                'approved_date': False,
            })

    def action_cancel(self):
        """Cancel the report."""
        for report in self:
            if report.state == 'posted':
                raise UserError(_('Cannot cancel a posted report.'))
            report.state = 'cancelled'

    def action_print(self):
        """Print the advance report."""
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_accounting.action_report_advance_report'
        ).report_action(self)


class AdvanceReportLine(models.Model):
    """Advance Report Expense Line."""
    _name = 'l10n_ua.advance.report.line'
    _description = 'Advance Report Line'
    _order = 'date, sequence, id'

    report_id = fields.Many2one(
        'l10n_ua.advance.report',
        string='Advance Report',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequence', default=10)

    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
    )
    description = fields.Char(
        string='Description',
        required=True,
    )

    # Document reference
    document_type = fields.Selection(
        selection=[
            ('receipt', 'Receipt/Check'),
            ('invoice', 'Invoice'),
            ('ticket', 'Ticket'),
            ('other', 'Other'),
        ],
        string='Document Type',
        default='receipt',
    )
    document_number = fields.Char(
        string='Document Number',
    )
    document_date = fields.Date(
        string='Document Date',
    )

    # Vendor
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
    )

    # Expense category
    expense_type = fields.Selection(
        selection=[
            ('transport', 'Transport'),
            ('accommodation', 'Accommodation'),
            ('meals', 'Meals'),
            ('fuel', 'Fuel'),
            ('supplies', 'Office Supplies'),
            ('other', 'Other'),
        ],
        string='Expense Type',
        required=True,
        default='other',
    )

    # Expense account (Дт) for the journal entry on posting
    account_id = fields.Many2one(
        'account.account',
        string='Expense Account',
        check_company=True,
        help='Account debited for this expense when the report is posted. '
             'If empty, the company default expense account is used.',
    )

    # Amount
    amount = fields.Monetary(
        string='Amount',
        required=True,
        currency_field='currency_id',
    )

    company_id = fields.Many2one(
        related='report_id.company_id',
        string='Company',
        store=True,
    )
    currency_id = fields.Many2one(
        related='report_id.currency_id',
        string='Currency',
    )

    # Attached document
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='Attachments',
        help='Attach receipt/invoice scan',
    )

    note = fields.Text(string='Note')
