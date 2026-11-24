"""Create deferral schedules (39/69) from invoice / bill lines — issue #372."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

DEFERRABLE_MOVE_TYPES = ('in_invoice', 'out_invoice', 'entry')


class L10nUaDeferralCreateWizard(models.TransientModel):
    _name = 'l10n_ua.deferral.create.wizard'
    _description = 'Defer Invoice Lines to Future Periods'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True)
    move_line_ids = fields.Many2many(
        'account.move.line',
        string='Lines to Defer',
        required=True,
        check_company=True,
        domain="[('company_id', '=', company_id), ('parent_state', '=', 'posted')]",
    )
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    method = fields.Selection(
        selection=[
            ('month', 'Equal monthly amounts'),
            ('day', 'Prorata by days'),
        ],
        string='Method',
        required=True,
        default='month',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        check_company=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
    )
    expense_deferral_account_id = fields.Many2one(
        'account.account',
        string='Deferred Expense Account (39)',
        check_company=True,
    )
    revenue_deferral_account_id = fields.Many2one(
        'account.account',
        string='Deferred Revenue Account (69)',
        check_company=True,
    )
    target_account_id = fields.Many2one(
        'account.account',
        string='Expense / Revenue Account',
        check_company=True,
        help='Only needed for lines booked directly on 39/69: the account the '
             'amount is recognised to. Lines booked on an expense/revenue '
             'account keep that account and are reclassified to 39/69.',
    )
    auto_confirm = fields.Boolean(
        string='Start Immediately',
        default=True,
        help='Compute the schedule and start it (post the reclassification '
             'entry) right away.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        lines = self.env['account.move.line']
        if ctx.get('active_model') == 'account.move':
            moves = self.env['account.move'].browse(ctx.get('active_ids') or [])
            lines = moves.invoice_line_ids if any(
                m.is_invoice() for m in moves) else moves.line_ids
            lines = lines.filtered(lambda l: l.display_type == 'product'
                                   or (l.move_id.move_type == 'entry'
                                       and not l.display_type))
        elif ctx.get('active_model') == 'account.move.line':
            lines = self.env['account.move.line'].browse(ctx.get('active_ids') or [])
        company = lines.company_id[:1] or self.env.company
        Deferral = self.env['l10n_ua.deferral']
        start = lines[:1].date or fields.Date.context_today(self)
        res.update({
            'company_id': company.id,
            'move_line_ids': [(6, 0, lines.ids)],
            'date_start': start,
            'date_end': start + relativedelta(years=1, days=-1),
            'journal_id': (company.l10n_ua_deferral_journal_id
                           or self.env['account.journal'].search([
                               ('type', '=', 'general'),
                               ('company_id', '=', company.id)], limit=1)).id,
            'expense_deferral_account_id':
                Deferral._get_default_deferral_account('expense', company).id,
            'revenue_deferral_account_id':
                Deferral._get_default_deferral_account('revenue', company).id,
        })
        return {k: v for k, v in res.items() if k in fields_list}

    @staticmethod
    def _line_kind(line):
        return 'expense' if line.balance > 0 else 'revenue'

    def _check_lines(self):
        for line in self.move_line_ids:
            if line.parent_state != 'posted':
                raise UserError(_(
                    'Line "%(line)s" of %(move)s is not posted. Post the '
                    'document before deferring it.',
                    line=line.name or line.account_id.display_name,
                    move=line.move_id.display_name))
            if line.move_id.move_type not in DEFERRABLE_MOVE_TYPES:
                raise UserError(_(
                    'Only vendor bills, customer invoices and journal entries '
                    'can be deferred (%s).', line.move_id.display_name))
            if line.company_currency_id.is_zero(line.balance):
                raise UserError(_('Line "%s" has no amount.', line.name or ''))
            active = line.l10n_ua_deferral_ids.filtered(
                lambda d: d.state != 'cancelled')
            if active:
                raise UserError(_(
                    'Line "%(line)s" is already deferred by %(deferral)s.',
                    line=line.name or line.account_id.display_name,
                    deferral=', '.join(active.mapped('name'))))

    def _prepare_deferral_vals(self, line):
        kind = self._line_kind(line)
        deferral_account = (self.expense_deferral_account_id if kind == 'expense'
                            else self.revenue_deferral_account_id)
        if not deferral_account:
            raise UserError(_(
                'Set the deferred %s account (39/69) in the wizard or in the '
                'company settings.',
                _('expense') if kind == 'expense' else _('revenue')))
        if line.account_id == deferral_account:
            target = self.target_account_id
            if not target:
                raise UserError(_(
                    'Line "%s" is booked on the deferral account itself: choose '
                    'the expense/revenue account to recognise it to.',
                    line.name or line.account_id.display_name))
        else:
            target = line.account_id
        return {
            'kind': kind,
            'company_id': line.company_id.id,
            'partner_id': line.partner_id.id,
            'description': line.name or line.move_id.ref or line.move_id.name,
            'source_move_line_id': line.id,
            'journal_id': self.journal_id.id,
            'deferral_account_id': deferral_account.id,
            'target_account_id': target.id,
            'analytic_distribution': line.analytic_distribution,
            'amount_total': abs(line.balance),
            'date_start': self.date_start,
            'date_end': self.date_end,
            'method': self.method,
        }

    def action_create(self):
        self.ensure_one()
        if self.date_end < self.date_start:
            raise UserError(_('The end date must not be earlier than the start date.'))
        self._check_lines()
        deferrals = self.env['l10n_ua.deferral'].create([
            self._prepare_deferral_vals(line) for line in self.move_line_ids])
        deferrals.action_compute_schedule()
        if self.auto_confirm:
            deferrals.action_confirm()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Deferrals'),
            'res_model': 'l10n_ua.deferral',
        }
        if len(deferrals) == 1:
            action.update(view_mode='form', res_id=deferrals.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', deferrals.ids)])
        return action


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    l10n_ua_deferral_ids = fields.One2many(
        'l10n_ua.deferral',
        'source_move_line_id',
        string='Deferrals (39/69)',
    )


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_ua_deferral_count = fields.Integer(
        string='Deferrals',
        compute='_compute_l10n_ua_deferral_count',
    )

    def _compute_l10n_ua_deferral_count(self):
        data = self.env['l10n_ua.deferral']._read_group(
            [('source_move_id', 'in', self.ids)],
            ['source_move_id'], ['__count'])
        counts = {move.id: count for move, count in data}
        for move in self:
            move.l10n_ua_deferral_count = counts.get(move.id, 0)

    def action_l10n_ua_defer(self):
        """«Розподілити як майбутніх періодів»: open the creation wizard."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Defer to Future Periods'),
            'res_model': 'l10n_ua.deferral.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move',
                'active_ids': self.ids,
            },
        }

    def action_l10n_ua_open_deferrals(self):
        self.ensure_one()
        deferrals = self.env['l10n_ua.deferral'].search(
            [('source_move_id', '=', self.id)])
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Deferrals'),
            'res_model': 'l10n_ua.deferral',
        }
        if len(deferrals) == 1:
            action.update(view_mode='form', res_id=deferrals.id)
        else:
            action.update(view_mode='list,form', domain=[('id', 'in', deferrals.ids)])
        return action
