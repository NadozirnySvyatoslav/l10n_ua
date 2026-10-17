"""Ukrainian Reconciliation Act (Акт звірки) wizard."""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ReconciliationActWizard(models.TransientModel):
    """Wizard for generating Ukrainian Reconciliation Act.

    Акт звірки взаєморозрахунків - a document that confirms mutual settlements
    between two parties (company and partner).
    """
    _name = 'l10n_ua.reconciliation.act.wizard'
    _description = 'Reconciliation Act Wizard'

    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        domain="['|', ('parent_id', '=', False), ('is_company', '=', True)]",
    )
    date_from = fields.Date(
        string='Date From',
        required=True,
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    account_type = fields.Selection(
        selection=[
            ('receivable', 'Receivable (Customers)'),
            ('payable', 'Payable (Vendors)'),
            ('both', 'Both'),
        ],
        string='Account Type',
        default='both',
        required=True,
    )
    include_unreconciled_only = fields.Boolean(
        string='Unreconciled Only',
        default=False,
        help='Show only unreconciled entries',
    )

    def action_print(self):
        """Generate and print Reconciliation Act."""
        self.ensure_one()

        if self.date_from > self.date_to:
            raise UserError(_('Date From must be before or equal to Date To.'))

        # Без data=: клієнт (getReportUrl) з непорожнім data будує URL
        # ?options=… без docids, і шаблон отримує порожні docs (#299).
        # Дані шаблон бере сам через wizard._get_report_data().
        return self.env.ref(
            'l10n_ua_accounting.action_report_reconciliation_act'
        ).report_action(self)

    def action_view_entries(self):
        """View journal entries for this partner and period."""
        self.ensure_one()

        domain = self._get_move_line_domain()

        return {
            'name': _('Journal Entries - %s') % self.partner_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'search_default_group_by_move': 1},
        }

    def _get_move_line_domain(self):
        """Get domain for account.move.line search."""
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('parent_state', '=', 'posted'),
        ]

        if self.account_type == 'receivable':
            domain.append(('account_id.account_type', '=', 'asset_receivable'))
        elif self.account_type == 'payable':
            domain.append(('account_id.account_type', '=', 'liability_payable'))
        else:
            domain.append(('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']))

        if self.include_unreconciled_only:
            domain.append(('amount_residual', '!=', 0))

        return domain

    def _get_opening_balance(self, account_types):
        """Calculate opening balance for partner accounts."""
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.balance), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE aml.partner_id = %s
              AND am.state = 'posted'
              AND aml.date < %s
              AND aa.account_type IN %s
        """, (self.partner_id.id, self.date_from, tuple(account_types)))

        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _get_report_data(self):
        """Get report data in format expected by QWeb template."""
        self.ensure_one()

        # Get account types to include
        if self.account_type == 'receivable':
            account_types = ['asset_receivable']
        elif self.account_type == 'payable':
            account_types = ['liability_payable']
        else:
            account_types = ['asset_receivable', 'liability_payable']

        # Calculate opening balance
        opening_balance = self._get_opening_balance(account_types)

        # Get all move lines for the period
        domain = self._get_move_line_domain()
        move_lines = self.env['account.move.line'].search(domain, order='date, id')

        # Prepare lines data
        lines = []
        running_balance = opening_balance

        for line in move_lines:
            debit = line.debit
            credit = line.credit
            running_balance += debit - credit

            lines.append({
                'date': line.date.strftime('%d.%m.%Y'),
                'ref': line.move_id.name,
                'name': line.name or line.move_id.ref or '-',
                'debit': debit,
                'credit': credit,
                'balance': running_balance,
            })

        # Calculate totals
        total_debit = sum(l['debit'] for l in lines)
        total_credit = sum(l['credit'] for l in lines)
        closing_balance = opening_balance + total_debit - total_credit

        return {
            'opening_balance': opening_balance,
            'closing_balance': closing_balance,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'lines': lines,
        }
