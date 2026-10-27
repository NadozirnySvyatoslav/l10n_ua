from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrFssSettlement(models.Model):
    """Взаєморозрахунки з ПФУ: заява-розрахунок, сальдо, відшкодування (#157, #499).

    З 01.01.2023 функції ФСС з матеріального забезпечення (допомога по
    тимчасовій непрацездатності з 6-го дня, по вагітності та пологах)
    виконує Пенсійний фонд України. Технічні імена (модель, поля, xml id)
    лишаються з «fss» для сумісності з наявними базами.

    Агрегує суми допомоги за лікарняними, що підлягають відшкодуванню Пенсійним фондом
    (частина з 6-го дня), відстежує сальдо до відшкодування, зіставляє фактично
    отримане відшкодування й формує сторнуючу проводку на невідшкодований залишок.
    """
    _name = 'hr.fss.settlement'
    _description = 'PFU Settlement (взаєморозрахунки з ПФУ)'
    _inherit = ['mail.thread']
    _order = 'date_to desc, id desc'

    name = fields.Char(string='Reference', required=True, default='New', copy=False)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id')
    date_from = fields.Date(string='Period From', required=True, tracking=True)
    date_to = fields.Date(string='Period To', required=True, tracking=True)

    sick_leave_ids = fields.One2many(
        'hr.sick.leave', 'fss_settlement_id', string='Sick Leaves')
    amount_accrued = fields.Monetary(
        string='Accrued (PFU)', compute='_compute_amounts', store=True,
        currency_field='currency_id',
        help='Сума допомоги за рахунок ПФУ (з 6-го дня) за лікарняними.')
    amount_received = fields.Monetary(
        string='Reimbursement Received', tracking=True,
        currency_field='currency_id')
    residual = fields.Monetary(
        string='PFU Debt (residual)', compute='_compute_amounts', store=True,
        currency_field='currency_id',
        help='Сальдо заборгованості ПФУ до відшкодування.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('partial', 'Partially Reimbursed'),
        ('reimbursed', 'Reimbursed'),
        ('written_off', 'Written Off'),
    ], string='Status', compute='_compute_state', store=True, tracking=True)

    date_submitted = fields.Date(string='Submitted On', readonly=True)
    date_reimbursed = fields.Date(string='Reimbursed On', readonly=True)

    # Проводка сторно невідшкодованого залишку
    journal_id = fields.Many2one('account.journal', string='Journal',
                                 domain="[('type', '=', 'general')]")
    expense_account_id = fields.Many2one(
        'account.account', string='Expense Account',
        help='Рахунок витрат для сторно невідшкодованої допомоги (Дт).')
    fss_receivable_account_id = fields.Many2one(
        'account.account', string='PFU Receivable Account',
        help='Рахунок розрахунків з ПФУ (Кт при сторно).')
    storno_move_id = fields.Many2one(
        'account.move', string='Storno Entry', readonly=True, copy=False)
    notes = fields.Text(string='Notes')

    @api.depends('sick_leave_ids.fss_amount', 'amount_received')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_accrued = sum(rec.sick_leave_ids.mapped('fss_amount'))
            rec.residual = rec.amount_accrued - rec.amount_received

    @api.depends('amount_accrued', 'amount_received', 'date_submitted',
                 'storno_move_id')
    def _compute_state(self):
        for rec in self:
            if rec.storno_move_id:
                rec.state = 'written_off'
            elif rec.amount_received <= 0:
                rec.state = 'submitted' if rec.date_submitted else 'draft'
            elif rec.residual > 0.01:
                rec.state = 'partial'
            else:
                rec.state = 'reimbursed'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.fss.settlement') or 'New'
        return super().create(vals_list)

    def action_gather_sick_leaves(self):
        """Підтягнути лікарняні періоду з сумою до відшкодування ПФУ."""
        self.ensure_one()
        leaves = self.env['hr.sick.leave'].search([
            ('company_id', '=', self.company_id.id),
            ('date_from', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
            ('fss_amount', '>', 0),
            ('fss_settlement_id', '=', False),
        ])
        leaves.write({'fss_settlement_id': self.id})
        return True

    def action_submit(self):
        for rec in self:
            if not rec.sick_leave_ids:
                raise UserError(_('Немає лікарняних для звірки з ПФУ.'))
            rec.date_submitted = fields.Date.context_today(rec)

    def action_register_reimbursement(self):
        """Зафіксувати дату отримання відшкодування (сума в amount_received)."""
        for rec in self:
            if rec.amount_received <= 0:
                raise UserError(_('Вкажіть отриману суму відшкодування.'))
            rec.date_reimbursed = fields.Date.context_today(rec)
        return True

    def action_write_off_unreimbursed(self):
        """Сторнуюча проводка на невідшкодований залишок (Дт витрати — Кт ПФУ)."""
        self.ensure_one()
        if self.residual <= 0.01:
            raise UserError(_('Немає невідшкодованого залишку для сторно.'))
        if not (self.journal_id and self.expense_account_id
                and self.fss_receivable_account_id):
            raise UserError(_(
                'Заповніть журнал і рахунки (витрати / розрахунки з ПФУ) '
                'для сторнуючої проводки.'))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': fields.Date.context_today(self),
            'ref': _('Сторно невідшкодованої допомоги ПФУ: %s') % self.name,
            'line_ids': [
                (0, 0, {'account_id': self.expense_account_id.id,
                        'debit': self.residual, 'credit': 0.0,
                        'name': _('Невідшкодовано ПФУ')}),
                (0, 0, {'account_id': self.fss_receivable_account_id.id,
                        'debit': 0.0, 'credit': self.residual,
                        'name': _('Невідшкодовано ПФУ')}),
            ],
        })
        self.storno_move_id = move.id
        self.message_post(body=_(
            'Сторно невідшкодованого залишку %.2f — проводка %s.'
        ) % (self.residual, move.name))
        return True

    _check_period = models.Constraint(
        'CHECK(date_to >= date_from)',
        'Кінець періоду не може бути раніше початку!',
    )
