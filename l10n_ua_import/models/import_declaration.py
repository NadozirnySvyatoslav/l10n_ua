import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.l10n_ua_account_vat.models.l10n_ua_tax_invoice import CUSTOMS_NUMBER_RE
from odoo.addons.stock_landed_costs.models.stock_landed_cost import SPLIT_METHOD

from .res_company import CUSTOMS_ACCOUNT_CODES, IMPORT_VAT_ACCOUNT_CODES

VAT_RATES = {'20': 0.20, '14': 0.14, '7': 0.07, 'exempt': 0.0}

# Митні платежі, що входять у собівартість (НП(С)БО 9 п. 9): поле МД і
# товар-послуга витрат на доставку (landed cost).
COST_PAYMENTS = (
    ('duty_amount', 'product_customs_duty'),
    ('excise_amount', 'product_import_excise'),
    ('fee_amount', 'product_customs_fee'),
)


class L10nUaImportDeclaration(models.Model):
    """Митна декларація на імпорт (ІМ-40).

    Мито, акциз і збори — у собівартість запасів через стандартні landed
    costs (Дт 281 Кт 377); ПДВ з МД — податковий кредит (Дт 6441 Кт 377) на
    дату сплати (п. 198.2, 187.8 ПКУ), підстава — сама МД (п. 201.12).
    """
    _name = 'l10n_ua.import.declaration'
    _description = 'Import Customs Declaration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Declaration Number', required=True, tracking=True, copy=False,
                       help='Номер митної декларації у форматі ЄАІС, напр. 26UA500020000123U4.')
    date = fields.Date(string='Clearance Date', required=True, tracking=True,
                       help='Дата митного оформлення (випуску у вільний обіг).')
    regime = fields.Selection([('im40', 'IM-40 Release for Free Circulation'), ('im41', 'IM-41 Re-import')],
                              string='Customs Regime', required=True, default='im40')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company Currency')
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, tracking=True)
    customs_office_id = fields.Many2one(
        'res.partner', string='Customs Office', required=True, tracking=True,
        default=lambda self: self.env.company.l10n_ua_import_customs_partner_id,
        help='Митниця, на користь якої сплачено митні платежі — контрагент у розрахунках (377) '
             'і в реєстрі податкових документів.')
    customs_office_code = fields.Char(string='Customs Office Code', help='Код митного органу, напр. UA500020.')
    agreement_id = fields.Many2one(
        'l10n_ua.agreement', string='Foreign Trade Contract', tracking=True,
        domain="[('l10n_ua_foreign_trade', '=', True), ('company_id', '=', company_id)]")
    incoterm_id = fields.Many2one(related='agreement_id.l10n_ua_incoterm_id')
    currency_id = fields.Many2one('res.currency', string='Contract Currency', required=True,
                                  compute='_compute_currency', store=True, readonly=False, precompute=True)
    bill_ids = fields.Many2many(
        'account.move', 'l10n_ua_import_declaration_move_rel', 'declaration_id', 'move_id',
        string='Vendor Bills', domain="[('move_type', '=', 'in_invoice'), ('state', '!=', 'cancel'), "
                                      "('company_id', '=', company_id)]")
    picking_ids = fields.Many2many(
        'stock.picking', 'l10n_ua_import_declaration_picking_rel', 'declaration_id', 'picking_id',
        string='Receipts', domain="[('picking_type_code', '=', 'incoming'), ('state', '=', 'done'), "
                                  "('company_id', '=', company_id)]")
    # --- вартість і платежі
    invoice_value = fields.Monetary(
        string='Invoice Value', currency_field='currency_id',
        compute='_compute_invoice_value', store=True, readonly=False,
        help='Фактурна вартість товарів у валюті контракту (без ПДВ).')
    exchange_rate = fields.Float(
        string='NBU Rate', digits=(12, 6), compute='_compute_exchange_rate', store=True, readonly=False,
        help='Курс НБУ на дату митного оформлення, гривень за одиницю валюти контракту (гр. 23 МД).')
    customs_value = fields.Monetary(
        string='Customs Value (UAH)', currency_field='company_currency_id',
        compute='_compute_customs_value', store=True, readonly=False,
        help='Митна вартість у гривнях (гр. 45 МД). За замовчуванням — фактурна вартість за курсом '
             'НБУ на дату оформлення; уточніть, якщо до неї додано доставку до кордону тощо.')
    duty_amount = fields.Monetary(string='Customs Duty', currency_field='company_currency_id', tracking=True)
    excise_amount = fields.Monetary(string='Excise Tax', currency_field='company_currency_id', tracking=True)
    fee_amount = fields.Monetary(string='Customs Fees', currency_field='company_currency_id', tracking=True)
    vat_rate = fields.Selection(
        [('20', '20%'), ('14', '14%'), ('7', '7%'), ('exempt', 'Exempt')],
        string='VAT Rate', required=True, default='20')
    vat_base = fields.Monetary(
        string='VAT Base', currency_field='company_currency_id', compute='_compute_vat', store=True,
        help='Митна вартість + мито + акциз (п. 190.1 ПКУ).')
    vat_amount = fields.Monetary(
        string='Import VAT', currency_field='company_currency_id', compute='_compute_vat', store=True)
    amount_customs_total = fields.Monetary(
        string='Customs Payments', currency_field='company_currency_id', compute='_compute_vat', store=True,
        help='Мито + акциз + збори + ПДВ — до сплати митниці.')
    vat_payment_date = fields.Date(
        string='Import VAT Paid On', compute='_compute_vat_payment_date', store=True, readonly=False,
        help='Дата сплати ПДВ за МД — дата податкового кредиту (п. 198.2, 187.8 ПКУ). Зазвичай '
             'збігається з датою оформлення, бо ПДВ сплачують до випуску товарів.')
    split_method = fields.Selection(
        SPLIT_METHOD, string='Split Method', required=True, default='by_current_cost_price',
        help='Як розподілити мито, акциз і збори між товарами надходжень.')
    bill_date_warning = fields.Boolean(compute='_compute_bill_date_warning')
    # --- результат
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted'), ('cancel', 'Cancelled')],
                             default='draft', required=True, tracking=True, copy=False)
    move_id = fields.Many2one('account.move', string='Import VAT Entry', readonly=True, copy=False)
    landed_cost_ids = fields.One2many('stock.landed.cost', 'l10n_ua_import_declaration_id',
                                      string='Landed Costs', readonly=True)
    tax_invoice_id = fields.Many2one('l10n_ua.tax.invoice', string='Tax Credit Document', readonly=True,
                                     copy=False)

    _name_company_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        'An import customs declaration with this number already exists.',
    )

    @api.depends('bill_ids.currency_id', 'agreement_id.currency_id')
    def _compute_currency(self):
        for declaration in self:
            declaration.currency_id = declaration.bill_ids[:1].currency_id or declaration.agreement_id.currency_id \
                or declaration.currency_id or declaration.company_id.currency_id

    @api.depends('bill_ids.amount_untaxed', 'currency_id')
    def _compute_invoice_value(self):
        for declaration in self:
            bills = declaration.bill_ids.filtered(lambda m: m.currency_id == declaration.currency_id)
            if bills:
                declaration.invoice_value = sum(bills.mapped('amount_untaxed'))

    @api.depends('currency_id', 'date', 'company_id')
    def _compute_exchange_rate(self):
        for declaration in self:
            company = declaration.company_id
            if not declaration.currency_id or not declaration.date:
                declaration.exchange_rate = declaration.exchange_rate or 1.0
                continue
            declaration.exchange_rate = declaration.currency_id._get_conversion_rate(
                declaration.currency_id, company.currency_id, company, declaration.date)

    @api.depends('invoice_value', 'exchange_rate')
    def _compute_customs_value(self):
        for declaration in self:
            declaration.customs_value = declaration.company_currency_id.round(
                declaration.invoice_value * declaration.exchange_rate)

    @api.depends('customs_value', 'duty_amount', 'excise_amount', 'fee_amount', 'vat_rate')
    def _compute_vat(self):
        for declaration in self:
            currency = declaration.company_currency_id
            declaration.vat_base = declaration.customs_value + declaration.duty_amount + declaration.excise_amount
            declaration.vat_amount = currency.round(declaration.vat_base * VAT_RATES[declaration.vat_rate])
            declaration.amount_customs_total = declaration.duty_amount + declaration.excise_amount \
                + declaration.fee_amount + declaration.vat_amount

    @api.depends('date')
    def _compute_vat_payment_date(self):
        for declaration in self:
            declaration.vat_payment_date = declaration.date

    @api.depends('bill_ids.invoice_date', 'date')
    def _compute_bill_date_warning(self):
        for declaration in self:
            declaration.bill_date_warning = bool(declaration.date and declaration.bill_ids.filtered(
                lambda m: m.invoice_date and m.invoice_date != declaration.date))

    @api.onchange('bill_ids')
    def _onchange_bills(self):
        bill = self.bill_ids[:1]
        if bill:
            self.partner_id = self.partner_id or bill.commercial_partner_id
            if not self.agreement_id and bill.l10n_ua_agreement_id.l10n_ua_foreign_trade:
                self.agreement_id = bill.l10n_ua_agreement_id
            if not self.picking_ids:
                self.picking_ids = bill.invoice_line_ids.purchase_order_id.picking_ids.filtered(
                    lambda p: p.picking_type_code == 'incoming' and p.state == 'done')

    # --- проведення

    def _cost_amount(self):
        return self.duty_amount + self.excise_amount + self.fee_amount

    def _check_can_post(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(self.env._('Only draft customs declarations can be posted.'))
        if not re.fullmatch(CUSTOMS_NUMBER_RE, self.name or ''):
            raise UserError(self.env._(
                'The customs declaration number %s is not in the EAIS format, e.g. 26UA500020000123U4.',
                self.name))
        if self.company_currency_id.compare_amounts(self.customs_value, 0.0) <= 0:
            raise UserError(self.env._('Set the customs value of the declaration %s.', self.name))
        currency = self.company_currency_id
        for field in ('duty_amount', 'excise_amount', 'fee_amount'):
            if currency.compare_amounts(self[field], 0.0) < 0:
                raise UserError(self.env._('Customs payments cannot be negative.'))
        if not currency.is_zero(self._cost_amount()) and not self.picking_ids:
            raise UserError(self.env._(
                'Link the receipts of the imported goods: the customs duty, excise and fees are '
                'added to their cost.'))

    def action_post(self):
        for declaration in self:
            declaration._check_can_post()
            company = declaration.company_id
            customs_account = company._l10n_ua_import_account(
                'l10n_ua_import_customs_account_id', CUSTOMS_ACCOUNT_CODES)
            if not customs_account:
                raise UserError(self.env._('Set the customs payments account in the accounting settings.'))
            declaration._post_landed_cost(customs_account)
            declaration._post_vat_entry(customs_account)
            declaration._create_tax_invoice()
            declaration.state = 'posted'
        return True

    def _post_landed_cost(self, customs_account):
        """Мито, акциз і збори — у собівартість товарів надходжень (Дт 281 Кт 377)."""
        self.ensure_one()
        currency = self.company_currency_id
        if currency.is_zero(self._cost_amount()):
            return
        lines = []
        labels = {
            'duty_amount': self.env._('Customs duty'),
            'excise_amount': self.env._('Import excise tax'),
            'fee_amount': self.env._('Customs fees'),
        }
        for field, product_xmlid in COST_PAYMENTS:
            if currency.is_zero(self[field]):
                continue
            product = self.env.ref(f'l10n_ua_import.{product_xmlid}')
            lines.append((0, 0, {
                'product_id': product.id,
                'name': f'{labels[field]} {self.name}',
                'price_unit': self[field],
                'split_method': self.split_method,
                'account_id': customs_account.id,
            }))
        landed_cost = self.env['stock.landed.cost'].with_company(self.company_id).create({
            'date': self.date,
            'company_id': self.company_id.id,
            'picking_ids': [(6, 0, self.picking_ids.ids)],
            'account_journal_id': (self.company_id.l10n_ua_import_journal_id
                                   or self.env['stock.landed.cost'].with_company(self.company_id)
                                   ._default_account_journal_id()).id,
            'description': self.env._('Customs declaration %s', self.name),
            'cost_lines': lines,
            'l10n_ua_import_declaration_id': self.id,
        })
        landed_cost.compute_landed_cost()
        landed_cost.button_validate()

    def _post_vat_entry(self, customs_account):
        """ПДВ з МД — податковий кредит: Дт 6441 Кт 377 на дату сплати."""
        self.ensure_one()
        company = self.company_id
        if self.company_currency_id.is_zero(self.vat_amount) or not company.l10n_ua_is_vat_payer:
            return
        vat_account = company._l10n_ua_import_account('l10n_ua_import_vat_account_id', IMPORT_VAT_ACCOUNT_CODES)
        journal = company._l10n_ua_import_journal()
        if not vat_account or not journal:
            raise UserError(self.env._('Set the import VAT account and the journal in the accounting settings.'))
        label = self.env._('Import VAT, customs declaration %s', self.name)
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.vat_payment_date or self.date,
            'ref': self.name,
            'line_ids': [
                (0, 0, {'account_id': vat_account.id, 'name': label, 'debit': self.vat_amount,
                        'partner_id': self.customs_office_id.id}),
                (0, 0, {'account_id': customs_account.id, 'name': label, 'credit': self.vat_amount,
                        'partner_id': self.customs_office_id.id}),
            ],
        })
        move.action_post()
        self.move_id = move

    def _create_tax_invoice(self):
        """Отриманий податковий документ з ознакою імпорту: МД — підстава для
        податкового кредиту (п. 201.12 ПКУ), рядки 11.x декларації з ПДВ."""
        self.ensure_one()
        if self.vat_rate == 'exempt' or not self.company_id.l10n_ua_is_vat_payer:
            return
        self.tax_invoice_id = self.env['l10n_ua.tax.invoice'].create({
            'invoice_type': 'received',
            'doc_type': 'pn',
            'number': self.name,
            'date': self.vat_payment_date or self.date,
            'vat_method': 'document',
            'partner_id': self.customs_office_id.id,
            'company_id': self.company_id.id,
            'move_id': self.move_id.id,
            'is_import': True,
            'received_status': 'received',
            'received_date': self.date,
            'contract_number': self.agreement_id.code or False,
            'contract_date': self.agreement_id.signature_date or self.agreement_id.start_date or False,
            'customs_number': self.name,
            'customs_date': self.date,
            'l10n_ua_import_declaration_id': self.id,
            'line_ids': [(0, 0, {
                'name': self.env._('Import of goods, customs declaration %s', self.name),
                'quantity': 1.0,
                'price_unit': self.vat_base,
                'vat_rate': self.vat_rate,
                'is_import': True,
            })],
        })

    def action_cancel(self):
        for declaration in self:
            if declaration.state == 'posted':
                declaration._reverse_postings()
        self.write({'state': 'cancel'})

    def _reverse_postings(self):
        """Сторно: від'ємні landed costs (проведені не скасовуються), сторно
        проведення ПДВ, скасування податкового документа."""
        self.ensure_one()
        for landed_cost in self.landed_cost_ids.filtered(lambda c: c.state == 'done'):
            if landed_cost.amount_total <= 0:
                continue
            reverse = landed_cost.copy({
                'date': fields.Date.context_today(self),
                'picking_ids': [(6, 0, landed_cost.picking_ids.ids)],
                'description': self.env._('Reversal of the customs declaration %s', self.name),
                'l10n_ua_import_declaration_id': self.id,
            })
            for line in reverse.cost_lines:
                line.price_unit = -line.price_unit
            reverse.compute_landed_cost()
            reverse.button_validate()
        if self.move_id.state == 'posted':
            self.move_id._reverse_moves([{
                'date': fields.Date.context_today(self),
                'ref': self.env._('Reversal of %s', self.move_id.ref),
            }], cancel=True)
        if self.tax_invoice_id:
            self.tax_invoice_id.action_cancel()

    def action_draft(self):
        for declaration in self:
            if declaration.state != 'cancel':
                raise UserError(self.env._('Only cancelled customs declarations can be reset to draft.'))
        self.write({'state': 'draft', 'move_id': False, 'tax_invoice_id': False})

    def unlink(self):
        if any(d.state == 'posted' for d in self):
            raise UserError(self.env._('Cancel the posted customs declaration before deleting it.'))
        return super().unlink()

    # --- навігація

    def action_view_landed_costs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.landed.cost',
            'name': self.env._('Landed Costs'),
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.landed_cost_ids.ids)],
        }

