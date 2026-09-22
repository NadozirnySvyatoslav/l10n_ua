"""Ukrainian Cash Book (Касова книга) wizard."""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CashBookWizard(models.TransientModel):
    """Wizard for generating Ukrainian Cash Book report.

    The Cash Book (Касова книга) is a mandatory document in Ukrainian accounting
    that records all cash transactions for a given period.
    """
    _name = 'l10n_ua.cash.book.wizard'
    _description = 'Cash Book Wizard'

    journal_id = fields.Many2one(
        'account.journal',
        string='Cash Journal',
        required=True,
        domain=[('type', '=', 'cash')],
    )
    date_from = fields.Date(
        string='Date From',
        required=True,
        default=fields.Date.context_today,
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

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            return {'domain': {'journal_id': [
                ('type', '=', 'cash'),
                ('company_id', '=', self.company_id.id),
            ]}}

    def action_print(self):
        """Generate and print Cash Book report."""
        self.ensure_one()

        if self.date_from > self.date_to:
            raise UserError(_('Date From must be before or equal to Date To.'))

        data = {
            'journal_id': self.journal_id.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'company_id': self.company_id.id,
        }

        return self.env.ref('l10n_ua_accounting.action_report_cash_book').report_action(self, data=data)

    def _get_cash_book_data(self):
        """Get cash book data for the report."""
        self.ensure_one()

        # Get the cash account for this journal
        cash_account = self.journal_id.default_account_id

        if not cash_account:
            raise UserError(_('Cash journal must have a default account configured.'))

        # Calculate opening balance
        opening_balance = self._get_opening_balance(cash_account)

        # Get all cash payments for the period
        payments = self.env['account.payment'].search([
            ('journal_id', '=', self.journal_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('state', 'in', ('paid', 'reconciled')),
        ], order='date, id')

        # Group by date
        lines_by_date = {}
        for payment in payments:
            date_key = payment.date
            if date_key not in lines_by_date:
                lines_by_date[date_key] = {
                    'date': date_key,
                    'lines': [],
                    'total_income': 0.0,
                    'total_expense': 0.0,
                }

            line_data = {
                'payment': payment,
                'document_number': payment.ua_cash_order_number or payment.name,
                'partner': payment.partner_id.name or '',
                'description': payment.memo or payment.ua_payment_basis or '',
                'income': payment.amount if payment.payment_type == 'inbound' else 0.0,
                'expense': payment.amount if payment.payment_type == 'outbound' else 0.0,
            }

            lines_by_date[date_key]['lines'].append(line_data)

            if payment.payment_type == 'inbound':
                lines_by_date[date_key]['total_income'] += payment.amount
            else:
                lines_by_date[date_key]['total_expense'] += payment.amount

        # Calculate running balances
        running_balance = opening_balance
        sorted_dates = sorted(lines_by_date.keys())

        for date_key in sorted_dates:
            day_data = lines_by_date[date_key]
            day_data['opening_balance'] = running_balance
            running_balance += day_data['total_income'] - day_data['total_expense']
            day_data['closing_balance'] = running_balance

        return {
            'journal': self.journal_id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'company': self.company_id,
            'opening_balance': opening_balance,
            'closing_balance': running_balance,
            'days': [lines_by_date[d] for d in sorted_dates],
            'total_income': sum(d['total_income'] for d in lines_by_date.values()),
            'total_expense': sum(d['total_expense'] for d in lines_by_date.values()),
        }

    def _get_opening_balance(self, account):
        """Calculate opening balance for cash account."""
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.balance), 0)
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.account_id = %s
              AND am.state = 'posted'
              AND aml.date < %s
        """, (account.id, self.date_from))

        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _get_report_data(self):
        """Get report data in format expected by QWeb template."""
        self.ensure_one()

        # Get the cash account for this journal
        cash_account = self.journal_id.default_account_id

        if not cash_account:
            raise UserError(_('Cash journal must have a default account configured.'))

        # Calculate opening balance
        opening_balance = self._get_opening_balance(cash_account)

        # Get all cash payments for the period
        payments = self.env['account.payment'].search([
            ('journal_id', '=', self.journal_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('state', 'in', ('paid', 'reconciled')),
        ], order='date, id')

        lines = []
        total_debit = 0.0
        total_credit = 0.0

        for payment in payments:
            debit = payment.amount if payment.payment_type == 'inbound' else 0.0
            credit = payment.amount if payment.payment_type == 'outbound' else 0.0

            lines.append({
                'number': payment.ua_cash_order_number or payment.name,
                'date': payment.date.strftime('%d.%m.%Y'),
                'partner': payment.partner_id.name or payment.ua_cash_person or '-',
                'account': payment.destination_account_id.code if payment.destination_account_id else '-',
                'debit': debit,
                'credit': credit,
            })

            total_debit += debit
            total_credit += credit

        closing_balance = opening_balance + total_debit - total_credit

        return {
            'opening_balance': opening_balance,
            'closing_balance': closing_balance,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'lines': lines,
        }
