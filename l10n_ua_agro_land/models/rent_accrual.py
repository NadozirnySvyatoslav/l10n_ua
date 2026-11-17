from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AgroRentAccrual(models.Model):
    """Нарахування орендної плати за землю за період.

    Орендар — податковий агент орендодавця-фізособи (ПКУ п. 170.1.1): з
    нарахованої плати утримує ПДФО 18 % (пп. 170.1.4, п. 167.1 ПКУ в ред.
    Закону № 5025-IX — ставка 5 % з 23.10.2026 стосується лише житлової/
    нежитлової нерухомості, не землі) і ВЗ 5 % (код доходу 106 у 4ДФ).
    Ставка копіюється в рядок нарахування, тож зміна налаштувань не змінює
    вже зроблених нарахувань.
    Проводка: Дт витрат (23/91) — Кт 685 (до виплати), 6411 (ПДФО), 642 (ВЗ).
    """
    _name = 'l10n_ua.agro.rent.accrual'
    _description = 'Land Rent Accrual'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(default='/', copy=False, readonly=True)
    date = fields.Date(
        string='Accounting Date', required=True, default=fields.Date.context_today, tracking=True)
    date_from = fields.Date(
        string='Period From', required=True,
        default=lambda self: date(fields.Date.context_today(self).year, 1, 1))
    date_to = fields.Date(
        string='Period To', required=True,
        default=lambda self: date(fields.Date.context_today(self).year, 12, 31))
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal())
    expense_account_id = fields.Many2one(
        'account.account', string='Expense Account', required=True,
        default=lambda self: self.env.company._l10n_ua_agro_account(
            'l10n_ua_agro_rent_expense_account_id', ('231', '23', '91')))
    payable_account_id = fields.Many2one(
        'account.account', string='Payable Account', required=True,
        default=lambda self: self.env.company._l10n_ua_agro_account(
            'l10n_ua_agro_rent_payable_account_id', ('6851', '685')))
    pdfo_account_id = fields.Many2one(
        'account.account', string='PIT Account', required=True,
        default=lambda self: self.env.company._l10n_ua_agro_account(
            'l10n_ua_agro_pdfo_account_id', ('6411', '641')))
    military_account_id = fields.Many2one(
        'account.account', string='Military Levy Account', required=True,
        default=lambda self: self.env.company._l10n_ua_agro_account(
            'l10n_ua_agro_military_account_id', ('6415', '642')))
    line_ids = fields.One2many(
        'l10n_ua.agro.rent.accrual.line', 'accrual_id', string='Lines', copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    amount_gross = fields.Monetary(string='Accrued', compute='_compute_totals', store=True)
    amount_pdfo = fields.Monetary(string='PIT', compute='_compute_totals', store=True)
    amount_military = fields.Monetary(string='Military Levy', compute='_compute_totals', store=True)
    amount_net = fields.Monetary(string='To Pay', compute='_compute_totals', store=True)
    amount_residual = fields.Monetary(string='Rent Debt', compute='_compute_residual')
    note = fields.Text()

    @api.model
    def _default_journal(self):
        company = self.env.company
        return company.l10n_ua_agro_rent_journal_id or self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', company.id),
        ], limit=1)

    @api.depends('line_ids.amount', 'line_ids.pdfo_amount',
                 'line_ids.military_amount', 'line_ids.net_amount')
    def _compute_totals(self):
        for accrual in self:
            lines = accrual.line_ids
            accrual.amount_gross = sum(lines.mapped('amount'))
            accrual.amount_pdfo = sum(lines.mapped('pdfo_amount'))
            accrual.amount_military = sum(lines.mapped('military_amount'))
            accrual.amount_net = sum(lines.mapped('net_amount'))

    @api.depends('line_ids.residual')
    def _compute_residual(self):
        for accrual in self:
            accrual.amount_residual = sum(accrual.line_ids.mapped('residual'))

    @api.constrains('date_from', 'date_to')
    def _check_period(self):
        for accrual in self:
            if accrual.date_from > accrual.date_to:
                raise ValidationError(self.env._('The period cannot end before it starts.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                company = self.env['res.company'].browse(
                    vals.get('company_id') or self.env.company.id)
                vals['name'] = self.env['ir.sequence'].with_company(company).next_by_code(
                    'l10n_ua.agro.rent.accrual') or '/'
        return super().create(vals_list)

    def unlink(self):
        if any(accrual.state == 'posted' for accrual in self):
            raise UserError(self.env._('Cancel the posted rent accrual before deleting it.'))
        return super().unlink()

    def action_compute(self):
        """Заповнити рядки за діючими в періоді договорами."""
        for accrual in self:
            if accrual.state != 'draft':
                raise UserError(self.env._('Only a draft accrual can be recomputed.'))
            accrual.line_ids.unlink()
            leases = self.env['l10n_ua.agro.land.lease'].search([
                ('company_id', '=', accrual.company_id.id),
                ('state', 'in', ('active', 'expired', 'terminated')),
                ('date_start', '<=', accrual.date_to),
                '|', ('date_end', '=', False), ('date_end', '>=', accrual.date_from),
            ], order='lessor_id, name')
            lines = []
            for lease in leases:
                amount = lease._period_rent(accrual.date_from, accrual.date_to)
                if amount:
                    lines.append(accrual._prepare_line(lease, amount))
            self.env['l10n_ua.agro.rent.accrual.line'].create(lines)
        return True

    def _prepare_line(self, lease, amount):
        self.ensure_one()
        company = self.company_id
        individual = lease.lessor_is_individual
        return {
            'accrual_id': self.id,
            'lease_id': lease.id,
            'amount': amount,
            'pdfo_rate': company.l10n_ua_agro_pdfo_rate if individual else 0.0,
            'military_rate': company.l10n_ua_agro_military_rate if individual else 0.0,
        }

    def action_post(self):
        for accrual in self:
            if accrual.state != 'draft':
                continue
            if not accrual.line_ids:
                raise UserError(self.env._('There is nothing to post: compute the lines first.'))
            move = self.env['account.move'].create(accrual._prepare_move_vals())
            move.action_post()
            accrual.write({'move_id': move.id, 'state': 'posted'})
        return True

    def _prepare_move_vals(self):
        self.ensure_one()
        lines = []
        for line in self.line_ids:
            partner = line.lessor_id.id
            label = self.env._('Land rent %(contract)s, %(date_from)s - %(date_to)s',
                               contract=line.lease_id.name, date_from=self.date_from,
                               date_to=self.date_to)
            lines.append((0, 0, {
                'name': label, 'account_id': self.expense_account_id.id,
                'partner_id': partner, 'debit': line.amount,
            }))
            lines.append((0, 0, {
                'name': label, 'account_id': self.payable_account_id.id,
                'partner_id': partner, 'credit': line.net_amount,
            }))
            if line.pdfo_amount:
                lines.append((0, 0, {
                    'name': self.env._('PIT on land rent, %s', line.lease_id.name),
                    'account_id': self.pdfo_account_id.id,
                    'partner_id': partner, 'credit': line.pdfo_amount,
                }))
            if line.military_amount:
                lines.append((0, 0, {
                    'name': self.env._('Military levy on land rent, %s', line.lease_id.name),
                    'account_id': self.military_account_id.id,
                    'partner_id': partner, 'credit': line.military_amount,
                }))
        return {
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.name,
            'company_id': self.company_id.id,
            'line_ids': lines,
        }

    def action_cancel(self):
        for accrual in self:
            if any(line.paid_amount for line in accrual.line_ids):
                raise UserError(self.env._(
                    'Rent under %s has already been paid: cancel the payments first.', accrual.name))
            if accrual.move_id:
                accrual.move_id.button_draft()
                accrual.move_id.button_cancel()
        self.write({'state': 'cancel'})

    def action_draft(self):
        for accrual in self:
            if accrual.state != 'cancel':
                raise UserError(self.env._('Cancel the accrual before resetting it to draft.'))
            move = accrual.move_id
            accrual.move_id = False
            if move:
                move.button_draft()
                move.unlink()
        self.write({'state': 'draft'})

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }


class AgroRentAccrualLine(models.Model):
    _name = 'l10n_ua.agro.rent.accrual.line'
    _description = 'Land Rent Accrual Line'
    _order = 'accrual_id, lessor_id, id'

    accrual_id = fields.Many2one(
        'l10n_ua.agro.rent.accrual', required=True, ondelete='cascade', index=True)
    state = fields.Selection(related='accrual_id.state', store=True)
    date = fields.Date(related='accrual_id.date', store=True)
    company_id = fields.Many2one(related='accrual_id.company_id', store=True)
    currency_id = fields.Many2one(related='accrual_id.currency_id')
    lease_id = fields.Many2one(
        'l10n_ua.agro.land.lease', string='Contract', required=True, ondelete='restrict', index=True)
    lessor_id = fields.Many2one(related='lease_id.lessor_id', store=True, index=True)
    lessor_vat = fields.Char(related='lessor_id.ipn', string='RNOKPP')
    katottg = fields.Char(
        compute='_compute_katottg', store=True,
        help='Громада за місцезнаходженням ділянки — туди сплачується ПДФО.')
    amount = fields.Monetary(string='Accrued', required=True)
    pdfo_rate = fields.Float(string='PIT %', digits=(5, 2))
    military_rate = fields.Float(string='Military Levy %', digits=(5, 2))
    pdfo_amount = fields.Monetary(string='PIT', compute='_compute_taxes', store=True)
    military_amount = fields.Monetary(string='Military Levy', compute='_compute_taxes', store=True)
    net_amount = fields.Monetary(string='To Pay', compute='_compute_taxes', store=True)
    payment_line_ids = fields.One2many(
        'l10n_ua.agro.rent.payment.line', 'accrual_line_id', string='Payments')
    paid_amount = fields.Monetary(string='Paid', compute='_compute_paid', store=True)
    residual = fields.Monetary(string='Debt', compute='_compute_paid', store=True)

    @api.depends('lease_id.plot_ids.katottg')
    def _compute_katottg(self):
        for line in self:
            line.katottg = (line.lease_id.plot_ids.filtered('katottg')[:1]).katottg or False

    @api.depends('amount', 'pdfo_rate', 'military_rate')
    def _compute_taxes(self):
        for line in self:
            currency = line.currency_id or self.env.company.currency_id
            line.pdfo_amount = currency.round(line.amount * line.pdfo_rate / 100.0)
            line.military_amount = currency.round(line.amount * line.military_rate / 100.0)
            line.net_amount = line.amount - line.pdfo_amount - line.military_amount

    @api.depends('net_amount', 'state', 'payment_line_ids.amount', 'payment_line_ids.state')
    def _compute_paid(self):
        for line in self:
            paid = sum(line.payment_line_ids.filtered(
                lambda p: p.state == 'posted').mapped('amount'))
            line.paid_amount = paid
            line.residual = line.net_amount - paid if line.state == 'posted' else 0.0

    @api.depends('accrual_id', 'lessor_id', 'lease_id')
    def _compute_display_name(self):
        for line in self:
            line.display_name = '%s / %s' % (line.accrual_id.name, line.lease_id.display_name)
