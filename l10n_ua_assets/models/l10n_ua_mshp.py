"""Low-value fast-wearing items (МШП, рах. 22) — transfer to operation,
off-balance quantity tracking and write-off."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaMshp(models.Model):
    _name = 'l10n_ua.mshp'
    _description = 'МШП (малоцінні швидкозношувані предмети)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Найменування',
        required=True,
        tracking=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Номенклатура',
        help='Необов’язкове посилання на номенклатуру.',
    )
    transfer_number = fields.Char(
        string='№ документа передачі',
        copy=False,
        readonly=True,
    )
    date = fields.Date(
        string='Дата передачі в експлуатацію',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    quantity = fields.Float(
        string='Кількість',
        default=1.0,
        required=True,
        tracking=True,
    )
    unit_cost = fields.Monetary(
        string='Ціна за одиницю',
        currency_field='currency_id',
        tracking=True,
    )
    total_cost = fields.Monetary(
        string='Вартість',
        compute='_compute_total_cost',
        store=True,
        currency_field='currency_id',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('in_use', 'В експлуатації'),
            ('written_off', 'Списано'),
        ],
        string='Стан',
        default='draft',
        required=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='МВО',
        help='Матеріально відповідальна особа.',
        tracking=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Підрозділ',
    )
    location = fields.Char(
        string='Місцезнаходження',
    )
    # --- Optional accounting (списання вартості на витрати при передачі) ---
    journal_id = fields.Many2one(
        'account.journal',
        string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal(),
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_expense_account(),
        help='Рахунок витрат, на який списується вартість при передачі '
             'в експлуатацію (92/93/949).',
    )
    stock_account_id = fields.Many2one(
        'account.account',
        string='Рахунок 22 (МШП)',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_stock_account(),
        help='Рахунок обліку МШП (22).',
    )
    move_id = fields.Many2one(
        'account.move',
        string='Проводка списання',
        readonly=True,
        copy=False,
    )
    # --- Write-off ---
    document_date = fields.Date(
        string='Дата документа',
        default=fields.Date.context_today,
        copy=False,
        help='Дата акту списання. Порожнє — сьогоднішня дата.',
    )
    writeoff_date = fields.Date(
        string='Дата списання',
        tracking=True,
    )
    writeoff_act_number = fields.Char(
        string='№ акту списання',
        copy=False,
        readonly=True,
    )
    writeoff_reason = fields.Text(
        string='Причина списання',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Компанія',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )
    notes = fields.Text(
        string='Примітки',
    )

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @api.model
    def _default_journal(self):
        return self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)],
            limit=1,
        )

    def _default_account_by_prefix(self, prefix):
        return self.env['account.account'].search([
            ('code', '=like', prefix + '%'),
            ('company_ids', 'in', self.env.company.id),
        ], limit=1)

    @api.model
    def _default_expense_account(self):
        return self._default_account_by_prefix('92')

    @api.model
    def _default_stock_account(self):
        return self._default_account_by_prefix('22')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('quantity', 'unit_cost')
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = rec.quantity * rec.unit_cost

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_transfer(self):
        """Передати МШП в експлуатацію: списати вартість + забалансовий облік."""
        for rec in self:
            if rec.state != 'draft':
                continue
            # The transfer is dated by «date»; the document date is kept for
            # the coming write-off act and must not carry the creation day.
            vals = {'state': 'in_use', 'document_date': False}
            if not rec.transfer_number:
                vals['transfer_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.mshp.transfer') or _('New')
            rec.write(vals)
            rec._create_transfer_move()

    def action_write_off(self):
        """Списати МШП із забалансового обліку (акт списання)."""
        for rec in self:
            if rec.state != 'in_use':
                raise UserError(_(
                    'Списати можна лише МШП в експлуатації: %s') % rec.name)
            writeoff_date = rec.document_date or fields.Date.context_today(self)
            if writeoff_date < rec.date:
                raise UserError(_(
                    'Дата списання МШП "%(name)s" (%(writeoff)s) не може бути '
                    'раніше дати передачі в експлуатацію (%(date)s).',
                    name=rec.display_name, writeoff=writeoff_date, date=rec.date))
            vals = {
                'state': 'written_off',
                'writeoff_date': writeoff_date,
                'document_date': False,
            }
            if not rec.writeoff_act_number:
                vals['writeoff_act_number'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.mshp.writeoff') or _('New')
            rec.write(vals)

    def action_draft(self):
        for rec in self:
            rec._reverse_transfer_move()
            rec.write({
                'state': 'draft',
                'writeoff_date': False,
                'writeoff_act_number': False,
                'writeoff_reason': False,
            })

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------

    def _create_transfer_move(self):
        """Дт витрати / Кт 22 на вартість переданих МШП (якщо задано рахунки)."""
        self.ensure_one()
        if self.move_id:
            return
        if not (self.journal_id and self.expense_account_id
                and self.stock_account_id):
            return
        amount = round(self.total_cost, 2)
        if amount <= 0:
            return
        move = self.env['account.move'].sudo().create({
            'move_type': 'entry',
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': _('Передача МШП в експлуатацію: %s') % self.name,
            'company_id': self.company_id.id,
            'line_ids': [
                (0, 0, {
                    'name': self.name,
                    'account_id': self.expense_account_id.id,
                    'debit': amount, 'credit': 0.0,
                }),
                (0, 0, {
                    'name': self.name,
                    'account_id': self.stock_account_id.id,
                    'debit': 0.0, 'credit': amount,
                }),
            ],
        })
        move.action_post()
        self.move_id = move

    def _reverse_transfer_move(self):
        self.ensure_one()
        if not self.move_id:
            return
        if self.move_id.state == 'posted':
            self.move_id._reverse_moves(
                default_values_list=[{'ref': _('Сторно: %s') % self.move_id.ref}],
                cancel=True,
            )
        else:
            self.move_id.unlink()
        self.move_id = False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_writeoff_act(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_ua_assets.action_report_mshp_writeoff').report_action(self)
