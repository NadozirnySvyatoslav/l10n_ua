"""Операції купівлі/продажу валюти (#205).

Документ обміну валюти з комерційним курсом банку та курсом НБУ:
- купівля: Дт 312 (за курсом НБУ) — Кт 311 (за комерційним курсом) + комісія;
- продаж: Кт 312 (за курсом НБУ) — Дт 311 (за комерційним) + комісія;
- різниця між комерційним курсом і курсом НБУ → фінрезультат операції
  (дохід 711 / витрати 942);
- комісія банку → витрати (92/949).
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaCurrencyExchange(models.Model):
    _name = 'l10n_ua.currency.exchange'
    _description = 'Купівля/продаж валюти'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Номер', required=True, copy=False, readonly=True, default='/')
    date = fields.Date(
        string='Дата операції', required=True,
        default=fields.Date.context_today, tracking=True)
    operation_type = fields.Selection(
        selection=[('purchase', 'Купівля валюти'), ('sale', 'Продаж валюти')],
        string='Операція', required=True, default='purchase', tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')

    foreign_currency_id = fields.Many2one(
        'res.currency', string='Валюта', required=True,
        domain="[('id', '!=', currency_id)]", tracking=True)
    fc_amount = fields.Monetary(
        string='Сума валюти', required=True,
        currency_field='foreign_currency_id', tracking=True)
    commercial_rate = fields.Float(
        string='Комерційний курс', digits=(16, 6), required=True, tracking=True,
        help='Курс банку (грн за одиницю валюти).')
    nbu_rate = fields.Float(
        string='Курс НБУ', digits=(16, 6), tracking=True,
        help='Офіційний курс НБУ на дату операції (грн за одиницю валюти).')
    commission = fields.Monetary(
        string='Комісія банку', currency_field='currency_id')

    # --- Computed amounts (у гривні) ---
    uah_amount = fields.Monetary(
        string='Сума в грн (комерц.)', compute='_compute_amounts', store=True,
        currency_field='currency_id',
        help='Сума операції за комерційним курсом (без комісії).')
    nbu_value = fields.Monetary(
        string='Вартість за курсом НБУ', compute='_compute_amounts', store=True,
        currency_field='currency_id')
    fx_result = fields.Monetary(
        string='Фінрезультат операції', compute='_compute_amounts', store=True,
        currency_field='currency_id',
        help='Різниця між комерційним курсом і курсом НБУ: '
             '>0 — дохід, <0 — витрати.')

    # --- Accounts ---
    journal_id = fields.Many2one(
        'account.journal', string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self._default_journal())
    foreign_account_id = fields.Many2one(
        'account.account', string='Валютний рахунок (312)',
        domain="[('company_ids', 'in', company_id)]",
        help='Рахунок обліку валютних коштів (312).')
    current_account_id = fields.Many2one(
        'account.account', string='Поточний рахунок (311)',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_account_prefix('311'))
    commission_account_id = fields.Many2one(
        'account.account', string='Рахунок витрат на комісію',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_account_prefix('92'))
    gain_account_id = fields.Many2one(
        'account.account', string='Дохід від операції (711)',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_gain_account())
    loss_account_id = fields.Many2one(
        'account.account', string='Витрати від операції (942)',
        domain="[('company_ids', 'in', company_id)]",
        default=lambda self: self._default_loss_account())

    state = fields.Selection(
        selection=[('draft', 'Чернетка'), ('posted', 'Проведено')],
        string='Стан', default='draft', required=True, tracking=True, copy=False)
    move_id = fields.Many2one(
        'account.move', string='Проводка', readonly=True, copy=False)
    note = fields.Text(string='Примітки')

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    @api.model
    def _default_journal(self):
        return self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)],
            limit=1)

    @api.model
    def _default_account_prefix(self, prefix):
        return self.env['account.account'].search([
            ('code', '=like', prefix + '%'),
            ('company_ids', 'in', self.env.company.id),
        ], limit=1)

    @api.model
    def _default_gain_account(self):
        return self.env.company.l10n_ua_fx_gain_op_account_id \
            or self._default_account_prefix('711')

    @api.model
    def _default_loss_account(self):
        return self.env.company.l10n_ua_fx_loss_op_account_id \
            or self._default_account_prefix('942')

    # ------------------------------------------------------------------
    # Compute / onchange
    # ------------------------------------------------------------------

    @api.depends('fc_amount', 'commercial_rate', 'nbu_rate', 'operation_type')
    def _compute_amounts(self):
        for rec in self:
            rec.uah_amount = rec.fc_amount * rec.commercial_rate
            rec.nbu_value = rec.fc_amount * rec.nbu_rate
            # Дохід/витрати від різниці комерційного курсу і курсу НБУ.
            if rec.operation_type == 'sale':
                # Продаж: виручка (комерц.) вища за НБУ → дохід.
                rec.fx_result = rec.uah_amount - rec.nbu_value
            else:
                # Купівля: заплатили (комерц.) більше за НБУ → витрати.
                rec.fx_result = rec.nbu_value - rec.uah_amount

    @api.onchange('foreign_currency_id', 'date')
    def _onchange_currency_rate(self):
        """Підставити курс НБУ з довідника курсів на дату операції."""
        for rec in self:
            if rec.foreign_currency_id and rec.date:
                # Курс = вартість 1 одиниці валюти в грн на дату.
                rate = rec.foreign_currency_id._l10n_ua_convert(
                    1.0, rec.company_id.currency_id, rec.company_id, rec.date)
                if rate:
                    rec.nbu_rate = rate

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'l10n_ua.currency.exchange') or '/'
        return super().create(vals_list)

    @api.constrains('fc_amount', 'commercial_rate')
    def _check_positive(self):
        for rec in self:
            if rec.fc_amount <= 0:
                raise UserError(_('Сума валюти має бути додатною.'))
            if rec.commercial_rate <= 0:
                raise UserError(_('Комерційний курс має бути додатним.'))

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    def _prepare_move_lines(self):
        """Збалансовані рядки проводки залежно від типу операції."""
        self.ensure_one()
        comp_cur = self.company_id.currency_id
        fc = self.foreign_currency_id
        uah = comp_cur.round(self.uah_amount)
        nbu = comp_cur.round(self.nbu_value)
        commission = comp_cur.round(self.commission)
        result = comp_cur.round(self.fx_result)
        lines = []

        if not (self.foreign_account_id and self.current_account_id):
            raise UserError(_(
                'Вкажіть валютний (312) і поточний (311) рахунки.'))

        if self.operation_type == 'purchase':
            # Дт 312 на вартість за курсом НБУ (+ валютний залишок).
            lines.append((0, 0, {
                'name': _('Купівля валюти %s') % fc.name,
                'account_id': self.foreign_account_id.id,
                'debit': nbu, 'credit': 0.0,
                'amount_currency': self.fc_amount,
                'currency_id': fc.id,
            }))
            # Кт 311 на суму за комерційним курсом + комісія.
            lines.append((0, 0, {
                'name': _('Оплата за валюту %s') % fc.name,
                'account_id': self.current_account_id.id,
                'debit': 0.0, 'credit': uah + commission,
            }))
            # Різниця (комерц. > НБУ → витрати; інакше дохід).
            if result < 0:
                lines.append((0, 0, {
                    'name': _('Витрати від купівлі валюти'),
                    'account_id': self._require(self.loss_account_id, 'loss').id,
                    'debit': -result, 'credit': 0.0,
                }))
            elif result > 0:
                lines.append((0, 0, {
                    'name': _('Дохід від купівлі валюти'),
                    'account_id': self._require(self.gain_account_id, 'gain').id,
                    'debit': 0.0, 'credit': result,
                }))
        else:
            # Продаж: Кт 312 за курсом НБУ (- валютний залишок).
            lines.append((0, 0, {
                'name': _('Продаж валюти %s') % fc.name,
                'account_id': self.foreign_account_id.id,
                'debit': 0.0, 'credit': nbu,
                'amount_currency': -self.fc_amount,
                'currency_id': fc.id,
            }))
            # Дт 311 на виручку за комерційним курсом мінус комісія.
            lines.append((0, 0, {
                'name': _('Виручка від продажу валюти %s') % fc.name,
                'account_id': self.current_account_id.id,
                'debit': uah - commission, 'credit': 0.0,
            }))
            # Різниця (комерц. > НБУ → дохід; інакше витрати).
            if result > 0:
                lines.append((0, 0, {
                    'name': _('Дохід від продажу валюти'),
                    'account_id': self._require(self.gain_account_id, 'gain').id,
                    'debit': 0.0, 'credit': result,
                }))
            elif result < 0:
                lines.append((0, 0, {
                    'name': _('Витрати від продажу валюти'),
                    'account_id': self._require(self.loss_account_id, 'loss').id,
                    'debit': -result, 'credit': 0.0,
                }))

        # Комісія банку → витрати.
        if commission:
            lines.append((0, 0, {
                'name': _('Комісія банку за операцію з валютою'),
                'account_id': self._require(
                    self.commission_account_id, 'commission').id,
                'debit': commission, 'credit': 0.0,
            }))
        return lines

    def _require(self, account, kind):
        labels = {
            'gain': _('доходу (711)'), 'loss': _('витрат (942)'),
            'commission': _('витрат на комісію'),
        }
        if not account:
            raise UserError(_(
                'Не вказано рахунок %s для операції з валютою.') % labels[kind])
        return account

    def action_post(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Операцію вже проведено.'))
        if not self.nbu_rate:
            raise UserError(_('Вкажіть курс НБУ на дату операції.'))
        journal = self.journal_id or self._default_journal()
        if not journal:
            raise UserError(_('Не знайдено загального журналу для проводки.'))
        lines = self._prepare_move_lines()
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': self.name,
            'company_id': self.company_id.id,
            'line_ids': lines,
        })
        move.action_post()
        self.write({'move_id': move.id, 'state': 'posted'})
        return True

    def action_draft(self):
        self.ensure_one()
        if self.move_id:
            if self.move_id.state == 'posted':
                self.move_id.button_draft()
            self.move_id.unlink()
        self.write({'move_id': False, 'state': 'draft'})
        return True

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
