"""Уцінка запасів до чистої вартості реалізації (НП(С)БО 9, п. 24–28) — #518.

На дату балансу запаси відображаються за меншою з оцінок: первісною вартістю
або чистою вартістю реалізації (п. 24). Чиста вартість реалізації — очікувана
ціна продажу мінус очікувані витрати на завершення і збут (п. 26, визначення
п. 4). Сума уцінки — витрати періоду, рахунок 946 «Втрати від знецінення
запасів» (п. 27); якщо ЧВР потім зростає, збільшення визнається доходом у межах
попередньої уцінки цього запасу — рахунок 719 «Інші доходи від операційної
діяльності» (п. 28). Матеріали для виробництва не уцінюються, якщо готова
продукція з них продаватиметься не нижче собівартості (п. 25) — ознака
«Не уцінювати» в рядку.

Вартість запасу змінюється рідним механізмом Odoo 19 (``product.value`` —
нова вартість одиниці на дату документа), тому складська оцінка й залишок
рахунку запасів у Головній книзі збігаються, і закриття оцінки запасів
(``action_close_stock_valuation``) уцінку не «повертає». Механізм діє для
середньозваженої (AVCO) і стандартної собівартості; для ФІФО Odoo не має
переоцінки залишку, тож такі товари документ не приймає.
"""
from datetime import datetime, time

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

SUPPORTED_COST_METHODS = ('average', 'standard')


class L10nUaInventoryWritedown(models.Model):
    _name = 'l10n_ua.inventory.writedown'
    _description = 'Inventory Write-down to Net Realisable Value'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date(
        string='Date', required=True, default=fields.Date.context_today,
        help='Balance sheet date at which inventories are measured (НП(С)БО 9, п. 24).')
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal())
    loss_account_id = fields.Many2one(
        'account.account', string='Write-down Loss Account',
        help='Account 946 «Втрати від знецінення запасів» (п. 27).')
    income_account_id = fields.Many2one(
        'account.account', string='Reversal Income Account',
        help='Account 719 «Інші доходи від операційної діяльності» (п. 28).')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True, copy=False)
    line_ids = fields.One2many(
        'l10n_ua.inventory.writedown.line', 'writedown_id', string='Lines', copy=True)
    total_writedown = fields.Monetary(string='Total Write-down', compute='_compute_totals', store=True)
    total_reversal = fields.Monetary(string='Total Reversal', compute='_compute_totals', store=True)
    note = fields.Text()

    @api.depends('date')
    def _compute_name(self):
        for rec in self:
            rec.name = _('Inventory write-down %s', rec.date.strftime('%d.%m.%Y')) \
                if rec.date else _('New')

    @api.depends('line_ids.writedown_amount', 'line_ids.reversal_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_writedown = sum(rec.line_ids.mapped('writedown_amount'))
            rec.total_reversal = sum(rec.line_ids.mapped('reversal_amount'))

    def _default_journal(self):
        return self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

    def _find_account(self, prefix):
        self.ensure_one()
        return self.env['account.account'].with_company(self.company_id).search([
            ('code', '=like', prefix + '%'),
            ('company_ids', 'parent_of', self.company_id.id),
        ], order='code', limit=1)

    def _set_default_accounts(self):
        for rec in self:
            rec.loss_account_id = rec.loss_account_id or rec._find_account('946')
            rec.income_account_id = rec.income_account_id or rec._find_account('719')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._set_default_accounts()
        return records

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.loss_account_id = self.income_account_id = False
        self._set_default_accounts()

    # ---------------------------------------------------------------- filling

    def _valuation_datetime(self):
        """Кінець дня документа: так Odoo рахує вартість «на дату» (to_date)."""
        self.ensure_one()
        return datetime.combine(self.date, time(23, 59, 59))

    def action_fill(self):
        """Рядки для всіх запасів компанії з залишком на дату документа.

        Наявні рядки товарів зберігаються разом із введеною ЧВР — оновлюються
        лише кількість і облікова вартість.
        """
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft write-down can be filled.'))
            products = self.env['product.product'].with_company(rec.company_id).search([
                ('is_storable', '=', True),
                ('company_id', 'in', [False, rec.company_id.id]),
            ])
            existing = {line.product_id: line for line in rec.line_ids}
            new_lines = []
            for product in products:
                if product in existing:
                    continue
                qty = product.with_context(to_date=rec._valuation_datetime()).qty_available
                if product.uom_id.compare(qty, 0) > 0:
                    new_lines.append({'writedown_id': rec.id, 'product_id': product.id})
            self.env['l10n_ua.inventory.writedown.line'].create(new_lines)
            rec.line_ids._refresh_book_value()
        return True

    # ---------------------------------------------------------------- posting

    def _check_postable(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft write-down can be posted.'))
        if not self.loss_account_id or not self.income_account_id:
            raise UserError(_('Set the write-down loss (946) and reversal income (719) accounts.'))
        fifo = self.line_ids.filtered(
            lambda l: l.product_id.with_company(self.company_id).cost_method
            not in SUPPORTED_COST_METHODS)
        if fifo:
            raise UserError(_(
                'Odoo cannot revalue the remaining stock of FIFO products: %s. '
                'Remove them from the write-down or switch the product category '
                'to average cost.', ', '.join(fifo.mapped('product_id.display_name'))))
        missing = self.line_ids.filtered(lambda l: not l.valuation_account_id
                                         and (l.writedown_amount or l.reversal_amount))
        if missing:
            raise UserError(_(
                'No stock valuation account for: %s. Set it on the product category '
                'or in the inventory settings.',
                ', '.join(missing.mapped('product_id.display_name'))))
        later = self.search([
            ('id', '!=', self.id), ('company_id', '=', self.company_id.id),
            ('state', '=', 'posted'), ('date', '>', self.date),
            ('line_ids.product_id', 'in', self.line_ids.product_id.ids),
        ], limit=1)
        if later:
            raise UserError(_(
                'A later write-down of the same goods is already posted: %s.', later.name))
        # Уцінка заднім числом: рухи після дати документа вже оцінено за старою
        # вартістю, нова вартість «на дату» розвела б склад і Головну книгу.
        moved = self.line_ids.filtered(lambda l: l.writedown_amount or l.reversal_amount) \
            ._done_moves([('date', '>', self._valuation_datetime())]).product_id
        if moved:
            raise UserError(_(
                'Stock moves after the document date are already done for: %s. '
                'Date the write-down on or after the last move.',
                ', '.join(moved.mapped('display_name'))))

    def action_post(self):
        for rec in self:
            if rec.state == 'draft':
                rec.line_ids._refresh_book_value()
            rec._check_postable()
            lines = rec.line_ids.filtered(lambda l: l.writedown_amount or l.reversal_amount)
            move = False
            if lines:
                move_lines = []
                for line in lines:
                    label = '%s: %s' % (rec.name, line.product_id.display_name)
                    if line.writedown_amount:
                        move_lines += [
                            (0, 0, {'account_id': rec.loss_account_id.id, 'name': label,
                                    'product_id': line.product_id.id,
                                    'debit': line.writedown_amount}),
                            (0, 0, {'account_id': line.valuation_account_id.id, 'name': label,
                                    'product_id': line.product_id.id,
                                    'credit': line.writedown_amount}),
                        ]
                    if line.reversal_amount:
                        move_lines += [
                            (0, 0, {'account_id': line.valuation_account_id.id, 'name': label,
                                    'product_id': line.product_id.id,
                                    'debit': line.reversal_amount}),
                            (0, 0, {'account_id': rec.income_account_id.id, 'name': label,
                                    'product_id': line.product_id.id,
                                    'credit': line.reversal_amount}),
                        ]
                move = self.env['account.move'].with_company(rec.company_id).create({
                    'move_type': 'entry',
                    'journal_id': rec.journal_id.id,
                    'date': rec.date,
                    'ref': rec.name,
                    'line_ids': move_lines,
                })
                move.action_post()
                lines._apply_new_value()
            rec.write({'state': 'posted', 'move_id': move and move.id})
        return True

    def action_cancel(self):
        """Сторно проводки; вартість запасу повертається до облікової до уцінки.

        Скасувати можна, лише поки товар не рухався після проведення: інакше
        частину уцінки вже списано в собівартість, і повне сторно датою
        документа розвело б склад і Головну книгу.
        """
        for rec in self:
            if rec.state != 'posted':
                continue
            if rec.move_id:
                # Пізніша — за датою; в межах однієї дати — за порядком проведення.
                later = self.search([
                    ('id', '!=', rec.id), ('company_id', '=', rec.company_id.id),
                    ('state', '=', 'posted'),
                    ('line_ids.product_id', 'in', rec.line_ids.product_id.ids),
                    '|', ('date', '>', rec.date),
                    '&', ('date', '=', rec.date), ('move_id', '>', rec.move_id.id),
                ], limit=1)
                if later:
                    raise UserError(_('Cancel the later write-down first: %s.', later.name))
                moved = rec.line_ids.filtered(
                    lambda l: (l.writedown_amount or l.reversal_amount)
                    and len(l._done_moves()) != l.done_move_count).product_id
                if moved:
                    raise UserError(_(
                        'The goods have moved since the write-down was posted: %s. '
                        'Post a new write-down (or a reversal) instead of cancelling.',
                        ', '.join(moved.mapped('display_name'))))
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id._reverse_moves(default_values_list=[{
                    'date': rec.date,
                    'ref': _('Reversal: %s', rec.name),
                }], cancel=True)
            rec.line_ids._restore_value()
            rec.write({'state': 'cancelled'})
        return True

    def action_draft(self):
        self.filtered(lambda r: r.state == 'cancelled').write(
            {'state': 'draft', 'move_id': False})
        return True

    def action_open_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def unlink(self):
        if any(rec.state == 'posted' for rec in self):
            raise UserError(_('Cancel a posted write-down before deleting it.'))
        return super().unlink()


class L10nUaInventoryWritedownLine(models.Model):
    _name = 'l10n_ua.inventory.writedown.line'
    _description = 'Inventory Write-down Line'
    _order = 'product_id'

    writedown_id = fields.Many2one(
        'l10n_ua.inventory.writedown', string='Write-down Document',
        required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='writedown_id.company_id', store=True)
    currency_id = fields.Many2one(related='writedown_id.currency_id')
    state = fields.Selection(related='writedown_id.state')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('is_storable', '=', True)]")
    uom_id = fields.Many2one(related='product_id.uom_id')
    quantity = fields.Float(
        string='Quantity', digits='Product Unit', readonly=True,
        help='Quantity on hand at the document date.')
    book_value = fields.Monetary(
        string='Book Value', readonly=True,
        help='Value of the quantity in stock valuation at the document date.')
    book_unit_cost = fields.Monetary(
        string='Unit Cost', compute='_compute_amounts', store=True)
    nrv_unit = fields.Monetary(
        string='Net Realisable Value per Unit',
        help='Expected selling price less the expected costs of completion and '
             'of selling (НП(С)БО 9, п. 4, 26).')
    nrv_set = fields.Boolean(
        string='NRV Entered',
        help='Set when the net realisable value is entered: a line without it '
             'is left at book value (an empty value is not a zero NRV).')
    exempt = fields.Boolean(
        string='Do Not Write Down',
        help='Raw materials and other supplies held for production are not '
             'written down when the finished goods they go into are expected to '
             'sell at or above cost (НП(С)БО 9, п. 25).')
    prior_writedown = fields.Monetary(
        string='Earlier Write-downs', readonly=True,
        help='Part of earlier posted write-downs of this product that is still in '
             'the quantity on hand: the limit of a reversal (п. 28). Updated by '
             '«Fill» and on posting.')
    prior_unit_writedown = fields.Float(
        string='Earlier Write-down per Unit', digits=(16, 6), readonly=True,
        help='Net write-down per unit by earlier posted documents.')
    prior_cost_cap = fields.Float(
        string='Unit Cost Before Write-downs', digits=(16, 6), readonly=True,
        help='Unit cost before the earlier write-downs: a reversal does not '
             'raise the cost above it.')
    done_move_count = fields.Integer(
        readonly=True, copy=False,
        help='Done stock moves of the product at posting: a cancel is refused '
             'once the goods have moved.')
    writedown_amount = fields.Monetary(
        string='Write-down', compute='_compute_amounts', store=True)
    reversal_amount = fields.Monetary(
        string='Reversal', compute='_compute_amounts', store=True)
    new_unit_cost = fields.Monetary(
        string='New Unit Cost', compute='_compute_amounts', store=True)
    valuation_account_id = fields.Many2one(
        'account.account', string='Stock Account', compute='_compute_valuation_account')
    previous_unit_cost = fields.Float(
        string='Unit Cost Before Posting', digits=(16, 6), readonly=True, copy=False,
        help='Stock valuation unit cost replaced by the posting; restored on cancel.')

    _product_uniq = models.Constraint(
        'UNIQUE(writedown_id, product_id)',
        'A product can be written down only once per document.',
    )
    _nrv_positive = models.Constraint(
        'CHECK(nrv_unit IS NULL OR nrv_unit >= 0)',
        'Net realisable value cannot be negative.',
    )

    @api.depends('product_id', 'company_id')
    def _compute_valuation_account(self):
        for line in self:
            product = line.product_id.with_company(line.company_id)
            accounts = product._get_product_accounts() if product else {}
            line.valuation_account_id = accounts.get('stock_valuation') \
                or line.company_id.account_stock_valuation_id

    def _prior_values(self, quantity, unit_cost):
        """Ліміт сторно (п. 28) від попередніх проведених уцінок товару.

        Ліміт — лише та частина уцінки, що припадає на поточний залишок:
        уцінка на одиницю × кількість, і нова ціна не вище ціни до уцінки
        (решту вже списано в собівартість проданого).
        """
        self.ensure_one()
        prior = self.search([
            ('product_id', '=', self.product_id.id),
            ('company_id', '=', self.company_id.id),
            ('writedown_id.state', '=', 'posted'),
            ('writedown_id.date', '<=', self.writedown_id.date),
            ('writedown_id', '!=', self.writedown_id.id),
            ('quantity', '>', 0),
        ])
        per_unit = max(0.0, sum(
            (p.writedown_amount - p.reversal_amount) / p.quantity for p in prior))
        cap = max(prior.filtered('writedown_amount').mapped('previous_unit_cost'), default=0.0)
        currency = self.currency_id or self.env.company.currency_id
        limit = currency.round(min(per_unit * quantity, max(0.0, cap - unit_cost) * quantity))
        return {
            'prior_unit_writedown': per_unit,
            'prior_cost_cap': cap,
            'prior_writedown': max(0.0, limit),
        }

    def _done_moves(self, extra_domain=None):
        """Виконані складські рухи товару рядка в компанії."""
        return self.env['stock.move'].search([
            ('product_id', 'in', self.product_id.ids),
            ('company_id', 'in', self.company_id.ids),
            ('state', '=', 'done'),
        ] + (extra_domain or []))

    @api.onchange('nrv_unit')
    def _onchange_nrv_unit(self):
        self.nrv_set = True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'nrv_unit' in vals and 'nrv_set' not in vals:
                vals['nrv_set'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'nrv_unit' in vals and 'nrv_set' not in vals:
            vals['nrv_set'] = True
        return super().write(vals)

    @api.depends('quantity', 'book_value', 'nrv_unit', 'nrv_set', 'exempt', 'prior_writedown')
    def _compute_amounts(self):
        for line in self:
            currency = line.currency_id or line.env.company.currency_id
            qty = line.quantity
            line.book_unit_cost = line.book_value / qty if qty else 0.0
            line.writedown_amount = line.reversal_amount = 0.0
            line.new_unit_cost = line.book_unit_cost
            if not qty or line.exempt or not line.nrv_set:
                continue
            # Вартість після операції — від ЧВР, а суму округлено до копійки.
            target = currency.round(line.nrv_unit * qty)
            difference = currency.round(line.book_value - target)
            if difference > 0:
                line.writedown_amount = difference
            elif difference < 0 and line.prior_writedown:
                line.reversal_amount = min(-difference, line.prior_writedown)
            change = line.reversal_amount - line.writedown_amount
            line.new_unit_cost = (line.book_value + change) / qty

    def _refresh_book_value(self):
        """Кількість і облікова вартість товару на дату документа (оцінка Odoo)."""
        for line in self:
            # Кінець дня документа: дата без часу дала б залишок на початок дня.
            product = line.product_id.with_company(line.company_id).with_context(
                to_date=line.writedown_id._valuation_datetime())
            qty = product.qty_available
            value = line.currency_id.round(product.total_value)
            # Суми рядка — stored compute від цих полів, тож у чернетці вони
            # не застарівають від прихованого пошуку; ліміт оновлюється тут.
            line.write({
                'quantity': qty,
                'book_value': value,
                **line._prior_values(qty, value / qty if qty else 0.0),
            })

    def _apply_new_value(self):
        """Нова вартість одиниці — запис ``product.value`` на дату документа.

        Для AVCO Odoo бере вартість з останнього ``product.value``, якщо він
        пізніший за останнє надходження, і рахує середню далі від неї; для
        стандартної собівартості вона ж — ціна на дату.
        """
        ProductValue = self.env['product.value'].sudo()
        for line in self.filtered(lambda l: l.writedown_amount or l.reversal_amount):
            product = line.product_id.with_company(line.company_id)
            line.write({
                'previous_unit_cost': line.book_unit_cost,
                'done_move_count': len(line._done_moves()),
            })
            ProductValue.with_company(line.company_id).create({
                'product_id': product.id,
                'company_id': line.company_id.id,
                'value': float_round(line.new_unit_cost, precision_digits=6),
                'date': line.writedown_id._valuation_datetime(),
                'description': line.writedown_id.name,
            })
            if product.cost_method == 'standard':
                product.sudo().with_context(disable_auto_revaluation=True).standard_price = \
                    line.new_unit_cost

    def _restore_value(self):
        ProductValue = self.env['product.value'].sudo()
        for line in self.filtered(lambda l: l.writedown_amount or l.reversal_amount):
            product = line.product_id.with_company(line.company_id)
            ProductValue.with_company(line.company_id).create({
                'product_id': product.id,
                'company_id': line.company_id.id,
                'value': line.previous_unit_cost,
                # Та сама мітка, що в уцінки: з однаковою датою Odoo бере
                # пізніший запис, а «зараз» могло б бути раніше кінця дня документа.
                'date': max(line.writedown_id._valuation_datetime(), fields.Datetime.now()),
                'description': _('Cancelled: %s', line.writedown_id.name),
            })
            if product.cost_method == 'standard':
                product.sudo().with_context(disable_auto_revaluation=True).standard_price = \
                    line.previous_unit_cost
