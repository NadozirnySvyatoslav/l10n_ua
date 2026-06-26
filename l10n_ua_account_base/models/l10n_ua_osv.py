from odoo import _, api, fields, models
from odoo.exceptions import UserError


class L10nUaOsv(models.Model):
    _name = 'l10n_ua.osv'
    _description = 'Trial Balance / OSV (Оборотно-сальдова відомість)'
    _order = 'period_start desc'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    period_start = fields.Date(
        string='Period Start',
        required=True,
    )
    period_end = fields.Date(
        string='Period End',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    line_ids = fields.One2many(
        'l10n_ua.osv.line',
        'osv_id',
        string='Lines',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
        ],
        string='State',
        default='draft',
    )
    osv_type = fields.Selection(
        selection=[
            ('synthetic', 'Synthetic'),
            ('analytic', 'Analytic'),
        ],
        string='Type',
        default='synthetic',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )

    @api.depends('period_start', 'period_end', 'osv_type')
    def _compute_name(self):
        for record in self:
            type_name = 'Synthetic' if record.osv_type == 'synthetic' else 'Analytic'
            if record.period_start:
                record.name = f'OSV {type_name} ({record.period_start} - {record.period_end})'
            else:
                record.name = 'New'

    def action_compute(self):
        """Compute OSV lines from posted account moves.

        Builds opening balance / period turnover / closing balance per account
        (and per partner for analytic OSV) from ``account.move.line``.
        """
        self.ensure_one()
        if not self.period_start or not self.period_end:
            raise UserError(_('Please set the period start and end dates.'))
        if self.period_end < self.period_start:
            raise UserError(_('Period end cannot be earlier than period start.'))

        self.line_ids.unlink()

        AML = self.env['account.move.line']
        analytic = self.osv_type == 'analytic'
        groupby = ['account_id', 'partner_id'] if analytic else ['account_id']
        empty_partner = self.env['res.partner']
        currency = self.company_id.currency_id

        base_domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]

        # key -> accumulator
        data = {}

        def bucket(account, partner):
            key = (account.id, partner.id)
            return data.setdefault(key, {
                'account': account,
                'partner': partner,
                'opening': 0.0,
                'turnover_debit': 0.0,
                'turnover_credit': 0.0,
            })

        # Opening balance: net of everything posted before the period start.
        opening_rows = AML._read_group(
            base_domain + [('date', '<', self.period_start)],
            groupby,
            ['balance:sum'],
        )
        for row in opening_rows:
            account = row[0]
            partner = row[1] if analytic else empty_partner
            bucket(account, partner)['opening'] += row[-1] or 0.0

        # Turnover: debit/credit movements within the period.
        turnover_rows = AML._read_group(
            base_domain + [
                ('date', '>=', self.period_start),
                ('date', '<=', self.period_end),
            ],
            groupby,
            ['debit:sum', 'credit:sum'],
        )
        for row in turnover_rows:
            account = row[0]
            partner = row[1] if analytic else empty_partner
            acc = bucket(account, partner)
            acc['turnover_debit'] += row[-2] or 0.0
            acc['turnover_credit'] += row[-1] or 0.0

        lines = []
        for acc in data.values():
            opening = acc['opening']
            turnover_debit = acc['turnover_debit']
            turnover_credit = acc['turnover_credit']
            closing = opening + turnover_debit - turnover_credit

            # Skip fully empty accounts (e.g. equal debit/credit netting to zero).
            if (currency.is_zero(opening)
                    and currency.is_zero(turnover_debit)
                    and currency.is_zero(turnover_credit)):
                continue

            lines.append((0, 0, {
                'account_id': acc['account'].id,
                'partner_id': acc['partner'].id or False,
                'opening_debit': opening if opening > 0 else 0.0,
                'opening_credit': -opening if opening < 0 else 0.0,
                'turnover_debit': turnover_debit,
                'turnover_credit': turnover_credit,
                'closing_debit': closing if closing > 0 else 0.0,
                'closing_credit': -closing if closing < 0 else 0.0,
            }))

        self.line_ids = lines
        return True

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_draft(self):
        self.write({'state': 'draft'})


class L10nUaOsvLine(models.Model):
    _name = 'l10n_ua.osv.line'
    _description = 'OSV Line'
    _order = 'account_id'

    osv_id = fields.Many2one(
        'l10n_ua.osv',
        string='OSV',
        required=True,
        ondelete='cascade',
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    opening_debit = fields.Monetary(
        string='Opening Debit',
        currency_field='currency_id',
    )
    opening_credit = fields.Monetary(
        string='Opening Credit',
        currency_field='currency_id',
    )
    turnover_debit = fields.Monetary(
        string='Turnover Debit',
        currency_field='currency_id',
    )
    turnover_credit = fields.Monetary(
        string='Turnover Credit',
        currency_field='currency_id',
    )
    closing_debit = fields.Monetary(
        string='Closing Debit',
        currency_field='currency_id',
    )
    closing_credit = fields.Monetary(
        string='Closing Credit',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='osv_id.currency_id',
    )
