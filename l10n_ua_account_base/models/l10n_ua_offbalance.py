"""Позабалансовий облік (клас 0) за простою системою (#256).

Інструкція про застосування Плану рахунків (наказ Мінфіну від 30.11.1999
№ 291), розділ «Клас 0. Позабалансові рахунки»: облік на рахунках класу 0
ведеться за простою системою — запис робиться лише за дебетом (надходження)
або лише за кредитом (вибуття), без кореспонденції з іншими рахунками.

Чому це окремий регістр, а не `account.move`:

* ядро вимагає балансу будь-якої проводки (`account.move._check_balanced`),
  а `account.move.line._check_off_balance` і так не дає змішувати рядки класу 0
  з балансовими. Послаблення перевірки балансу означало б перевизначати
  приватний метод ядра (`_get_unbalanced_moves`), на який спираються звірка,
  сторнування, різниці курсів, експорти й звіти ядра та Enterprise, — і
  кожне оновлення Odoo ставило б це під ризик;
* записи класу 0 не мають жодного впливу на баланс, тож ОСВ і Форма № 1
  (що читають `account.move.line`) не бачать регістру за побудовою, а не
  завдяки фільтру, який хтось колись забуде;
* предмет позабалансового обліку — речі, що належать іншим (орендоване
  майно, ТМЦ на відповідальному зберіганні, бланки суворого обліку), тому
  поруч із сумою потрібна кількість — у регістрі вона є від початку.

Звіт за регістром — `l10n_ua.offbalance.osv` (ОСВ по класу 0).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class L10nUaOffbalanceMove(models.Model):
    _name = 'l10n_ua.offbalance.move'
    _description = 'Off-Balance Entry (Class 0)'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'
    _check_company_auto = True

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
    ref = fields.Char(
        string='Basis Document',
        help='Документ-підстава: договір оренди, акт приймання на зберігання, '
             'накладна на бланки тощо.',
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
        related='company_id.currency_id',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancel', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )
    line_ids = fields.One2many(
        'l10n_ua.offbalance.move.line',
        'move_id',
        string='Lines',
        copy=True,
    )
    narration = fields.Text(string='Notes')

    def _check_lock_date(self):
        for move in self:
            if move.company_id._get_lock_date_violations(
                    move.date, fiscalyear=True, sale=False, purchase=False,
                    tax=False, hard=True):
                raise UserError(_(
                    'Дата запису %(date)s потрапляє в закритий період компанії '
                    '%(company)s.', date=move.date, company=move.company_id.name))

    def action_post(self):
        for move in self:
            if move.state != 'draft':
                raise UserError(_('Провести можна лише чернетку.'))
            if not move.line_ids:
                raise UserError(_('Запис позабалансового обліку не має рядків.'))
        self._check_lock_date()
        for move in self:
            vals = {'state': 'posted'}
            if move.name == '/':
                vals['name'] = self.env['ir.sequence'].with_company(
                    move.company_id).next_by_code(
                        'l10n_ua.offbalance.move', sequence_date=move.date) or '/'
            move.write(vals)
        return True

    def action_cancel(self):
        self._check_lock_date()
        self.write({'state': 'cancel'})
        return True

    def action_draft(self):
        self._check_lock_date()
        self.write({'state': 'draft'})
        return True

    # Поля, які можна міняти в проведеному документі: службові та чатер.
    _POSTED_EDITABLE = {'state', 'name', 'narration', 'message_main_attachment_id'}

    def write(self, vals):
        if set(vals) - self._POSTED_EDITABLE and any(
                move.state == 'posted' for move in self):
            raise UserError(_(
                'Проведений запис позабалансового обліку змінювати не можна — '
                'спершу поверніть його в чернетку.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if any(move.state == 'posted' for move in self):
            raise UserError(_(
                'Проведений запис позабалансового обліку видаляти не можна.'))


class L10nUaOffbalanceMoveLine(models.Model):
    _name = 'l10n_ua.offbalance.move.line'
    _description = 'Off-Balance Entry Line (Class 0)'
    _order = 'date desc, move_id desc, sequence, id'
    _check_company_auto = True

    move_id = fields.Many2one(
        'l10n_ua.offbalance.move',
        string='Entry',
        required=True,
        index=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    date = fields.Date(related='move_id.date', store=True, index=True)
    state = fields.Selection(related='move_id.state', store=True, index=True)
    company_id = fields.Many2one(
        related='move_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='move_id.currency_id')
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
        index=True,
        check_company=True,
        domain="[('account_type', '=', 'off_balance')]",
    )
    direction = fields.Selection(
        selection=[
            ('debit', 'Receipt (Debit)'),
            ('credit', 'Disposal (Credit)'),
        ],
        string='Direction',
        required=True,
        default='debit',
        help='Проста система: запис лише за дебетом (надходження) або лише '
             'за кредитом (вибуття), без кореспондуючого рахунку.',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        index=True,
        help='Власник майна, орендодавець, поклажодавець чи гарант.',
    )
    name = fields.Char(string='Item', required=True)
    quantity = fields.Float(string='Quantity', digits='Product Unit', default=0.0)
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    debit = fields.Monetary(
        string='Debit', currency_field='currency_id',
        compute='_compute_debit_credit', store=True)
    credit = fields.Monetary(
        string='Credit', currency_field='currency_id',
        compute='_compute_debit_credit', store=True)
    quantity_in = fields.Float(
        string='Qty In', digits='Product Unit',
        compute='_compute_debit_credit', store=True)
    quantity_out = fields.Float(
        string='Qty Out', digits='Product Unit',
        compute='_compute_debit_credit', store=True)

    _check_amount_positive = models.Constraint(
        'CHECK(amount >= 0 AND quantity >= 0)',
        'Сума й кількість у записі позабалансового обліку не можуть бути '
        "від'ємними: напрям задає поле «Напрям».",
    )

    @api.depends('direction', 'amount', 'quantity')
    def _compute_debit_credit(self):
        for line in self:
            is_debit = line.direction == 'debit'
            line.debit = line.amount if is_debit else 0.0
            line.credit = 0.0 if is_debit else line.amount
            line.quantity_in = line.quantity if is_debit else 0.0
            line.quantity_out = 0.0 if is_debit else line.quantity

    @api.constrains('account_id')
    def _check_account_off_balance(self):
        for line in self:
            if line.account_id.account_type != 'off_balance':
                raise ValidationError(_(
                    'Рахунок %s не позабалансовий: у регістр класу 0 можна '
                    'записувати лише рахунки типу «Позабалансовий».',
                    line.account_id.display_name))

    @api.constrains('amount', 'quantity')
    def _check_not_empty(self):
        for line in self:
            if line.currency_id.is_zero(line.amount) and not line.quantity:
                raise ValidationError(_(
                    'Рядок «%s» не має ні суми, ні кількості.', line.name))

    @api.model_create_multi
    def create(self, vals_list):
        moves = self.env['l10n_ua.offbalance.move'].browse(
            [vals['move_id'] for vals in vals_list if vals.get('move_id')])
        self._raise_if_posted(moves)
        return super().create(vals_list)

    def write(self, vals):
        self._raise_if_posted(self.move_id)
        if vals.get('move_id'):
            self._raise_if_posted(
                self.env['l10n_ua.offbalance.move'].browse(vals['move_id']))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        self._raise_if_posted(self.move_id)

    @api.model
    def _raise_if_posted(self, moves):
        if any(move.state == 'posted' for move in moves):
            raise UserError(_(
                'Рядки проведеного запису позабалансового обліку змінювати не '
                'можна — спершу поверніть запис у чернетку.'))


class L10nUaOffbalanceOsv(models.Model):
    """ОСВ по класу 0 — за регістром позабалансового обліку, не за проводками.

    Окремо від `l10n_ua.osv`: там сума оборотів Дт дорівнює сумі оборотів Кт
    (подвійний запис), а тут — ні, і змішування зламало б цю звірку.
    """
    _name = 'l10n_ua.offbalance.osv'
    _description = 'Off-Balance Trial Balance (Class 0)'
    _order = 'period_start desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    period_start = fields.Date(string='Period Start', required=True)
    period_end = fields.Date(string='Period End', required=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id')
    account_id = fields.Many2one(
        'account.account', string='Account',
        domain="[('account_type', '=', 'off_balance')]",
        help='Обмежити відомість одним рахунком класу 0 (опційно).')
    by_partner = fields.Boolean(
        string='By Partner',
        help='Розгорнути рахунки за контрагентами (власник, орендодавець, гарант).')
    line_ids = fields.One2many(
        'l10n_ua.offbalance.osv.line', 'osv_id', string='Lines')

    @api.depends('period_start', 'period_end')
    def _compute_name(self):
        for rec in self:
            rec.name = _('ОСВ клас 0 (%(start)s – %(end)s)',
                         start=rec.period_start or '', end=rec.period_end or '')

    def action_compute(self):
        self.ensure_one()
        if self.period_end < self.period_start:
            raise UserError(_('Period end cannot be earlier than period start.'))
        self.line_ids.unlink()

        Line = self.env['l10n_ua.offbalance.move.line']
        domain = [('state', '=', 'posted'), ('company_id', '=', self.company_id.id)]
        if self.account_id:
            domain.append(('account_id', '=', self.account_id.id))
        groupby = ['account_id'] + (['partner_id'] if self.by_partner else [])
        aggregates = ['debit:sum', 'credit:sum', 'quantity_in:sum', 'quantity_out:sum']

        data = {}

        def bucket(row):
            partner = row[1] if self.by_partner else self.env['res.partner']
            return data.setdefault((row[0].id, partner.id), {
                'account_id': row[0].id, 'partner_id': partner.id,
                'opening': 0.0, 'opening_qty': 0.0,
                'turnover_debit': 0.0, 'turnover_credit': 0.0,
                'quantity_in': 0.0, 'quantity_out': 0.0,
            })

        n = len(groupby)
        for row in Line._read_group(
                domain + [('date', '<', self.period_start)], groupby, aggregates):
            debit, credit, q_in, q_out = row[n:]
            acc = bucket(row)
            acc['opening'] += debit - credit
            acc['opening_qty'] += q_in - q_out
        for row in Line._read_group(
                domain + [('date', '>=', self.period_start),
                          ('date', '<=', self.period_end)], groupby, aggregates):
            debit, credit, q_in, q_out = row[n:]
            acc = bucket(row)
            acc['turnover_debit'] += debit
            acc['turnover_credit'] += credit
            acc['quantity_in'] += q_in
            acc['quantity_out'] += q_out

        currency = self.currency_id
        lines = []
        for acc in data.values():
            opening = acc.pop('opening')
            closing = opening + acc['turnover_debit'] - acc['turnover_credit']
            closing_qty = acc['opening_qty'] + acc['quantity_in'] - acc['quantity_out']
            if all(currency.is_zero(v) for v in (opening, acc['turnover_debit'],
                                                 acc['turnover_credit'])) \
                    and not any((acc['opening_qty'], acc['quantity_in'],
                                 acc['quantity_out'])):
                continue
            lines.append((0, 0, dict(
                acc,
                opening_debit=max(opening, 0.0),
                opening_credit=max(-opening, 0.0),
                closing_debit=max(closing, 0.0),
                closing_credit=max(-closing, 0.0),
                closing_qty=closing_qty,
            )))
        self.line_ids = lines
        return True


class L10nUaOffbalanceOsvLine(models.Model):
    _name = 'l10n_ua.offbalance.osv.line'
    _description = 'Off-Balance Trial Balance Line'
    _order = 'account_id, partner_id'

    osv_id = fields.Many2one(
        'l10n_ua.offbalance.osv', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='osv_id.currency_id')
    account_id = fields.Many2one('account.account', string='Account', required=True)
    partner_id = fields.Many2one('res.partner', string='Partner')
    opening_debit = fields.Monetary(string='Opening Debit', currency_field='currency_id')
    opening_credit = fields.Monetary(string='Opening Credit', currency_field='currency_id')
    turnover_debit = fields.Monetary(string='Turnover Debit', currency_field='currency_id')
    turnover_credit = fields.Monetary(string='Turnover Credit', currency_field='currency_id')
    closing_debit = fields.Monetary(string='Closing Debit', currency_field='currency_id')
    closing_credit = fields.Monetary(string='Closing Credit', currency_field='currency_id')
    opening_qty = fields.Float(string='Opening Qty', digits='Product Unit')
    quantity_in = fields.Float(string='Qty In', digits='Product Unit')
    quantity_out = fields.Float(string='Qty Out', digits='Product Unit')
    closing_qty = fields.Float(string='Closing Qty', digits='Product Unit')
