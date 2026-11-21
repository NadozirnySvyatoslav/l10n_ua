"""Wizard to mass-create bank payment orders from unpaid vendor bills."""

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class PaymentOrderWizard(models.TransientModel):
    _name = 'l10n_ua.payment.order.wizard'
    _description = 'Create Payment Orders from Vendor Bills'

    journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        domain="[('type', '=', 'bank')]",
    )
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    line_ids = fields.One2many(
        'l10n_ua.payment.order.wizard.line',
        'wizard_id',
        string='Bills to Pay',
    )
    total_amount = fields.Monetary(
        string='Total',
        compute='_compute_total_amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
    )

    @api.depends('line_ids.amount_to_pay')
    def _compute_total_amount(self):
        for wiz in self:
            wiz.total_amount = sum(wiz.line_ids.mapped('amount_to_pay'))

    @api.model
    def default_get(self, fields_list):
        """Pre-populate lines from selected vendor bills."""
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids', [])
        active_model = self.env.context.get('active_model')

        if active_model == 'account.move' and active_ids:
            bills = self.env['account.move'].browse(active_ids).filtered(
                lambda m: m.move_type == 'in_invoice'
                and m.state == 'posted'
                and m.amount_residual > 0
            )
            lines = []
            for bill in bills:
                partner_bank = bill.partner_id.bank_ids[:1]
                lines.append((0, 0, {
                    'bill_id': bill.id,
                    'amount_residual': bill.amount_residual,
                    'amount_to_pay': bill.amount_residual,
                    'partner_bank_id': partner_bank.id if partner_bank else False,
                    'currency_id': bill.currency_id.id,
                }))
            if lines:
                res['line_ids'] = lines

        # Default bank journal
        if 'journal_id' in fields_list and not res.get('journal_id'):
            bank_journal = self.env['account.journal'].search([
                ('type', '=', 'bank'),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if bank_journal:
                res['journal_id'] = bank_journal.id

        return res

    def _generate_payment_purpose(self, bill, partner):
        """Generate standard Ukrainian payment purpose text."""
        parts = []
        parts.append(f"Оплата за рах. {bill.name or bill.ref or ''}")
        if bill.invoice_date:
            parts.append(f"від {bill.invoice_date.strftime('%d.%m.%Y')}")
        purpose = ' '.join(parts)

        if partner.edrpou:
            purpose += f", ЄДРПОУ {partner.edrpou}"

        if bill.amount_tax:
            purpose += f", в т.ч. ПДВ {bill.amount_tax:.2f} грн"
        else:
            purpose += ", без ПДВ"

        return purpose

    def action_create_payment_orders(self):
        """Create account.payment records for each line."""
        self.ensure_one()
        payments = self.env['account.payment']

        for line in self.line_ids:
            if line.amount_to_pay <= 0:
                continue

            purpose = self._generate_payment_purpose(line.bill_id, line.bill_id.partner_id)

            payment_vals = {
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': line.bill_id.partner_id.id,
                'partner_bank_id': line.partner_bank_id.id if line.partner_bank_id else False,
                'amount': line.amount_to_pay,
                'currency_id': line.currency_id.id,
                'journal_id': self.journal_id.id,
                'date': self.payment_date,
                'memo': line.bill_id.name or '',
                'ua_payment_purpose': purpose,
            }
            payment = self.env['account.payment'].create(payment_vals)
            payments |= payment

        if not payments:
            raise UserError(_('No payment orders to create. Check amounts.'))

        action = {
            'name': _('Платіжні доручення'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'domain': [('id', 'in', payments.ids)],
        }
        if len(payments) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = payments.id
        else:
            action['view_mode'] = 'list,form'
        return action


class PaymentOrderWizardLine(models.TransientModel):
    _name = 'l10n_ua.payment.order.wizard.line'
    _description = 'Payment Order Wizard Line'

    wizard_id = fields.Many2one(
        'l10n_ua.payment.order.wizard',
        required=True,
        ondelete='cascade',
    )
    bill_id = fields.Many2one(
        'account.move',
        string='Vendor Bill',
        required=True,
    )
    partner_id = fields.Many2one(
        related='bill_id.partner_id',
        string='Vendor',
    )
    amount_residual = fields.Monetary(
        string='Amount Due',
        readonly=True,
        currency_field='currency_id',
    )
    amount_to_pay = fields.Monetary(
        string='Amount to Pay',
        currency_field='currency_id',
    )
    partner_bank_id = fields.Many2one(
        'res.partner.bank',
        string='Recipient Account',
        domain="[('partner_id', '=', partner_id)]",
    )
    currency_id = fields.Many2one('res.currency')

    @api.constrains('amount_to_pay', 'amount_residual')
    def _check_amount(self):
        for line in self:
            if line.amount_to_pay > line.amount_residual + 0.01:
                raise ValidationError(_('Amount to pay cannot exceed amount due.'))
            if line.amount_to_pay < 0:
                raise ValidationError(_('Amount to pay cannot be negative.'))
