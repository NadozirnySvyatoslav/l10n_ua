from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountBankStatement(models.Model):
    """Native-виписка з метаданими джерела імпорту (Фаза 1 рефактора).

    Виписка формується В ПРОЦЕСІ імпорту як унікальна сутність: несе дату й
    джерело завантаження (файл/API + посилання), а баланси беруться з джерела.
    `l10n_ua_balance_verified` фіксує, чи баланси реально отримані з джерела
    (тоді balance_start + Σ = balance_end — контроль повноти), чи виведені
    постфактум (недостовірний контроль).
    """
    _inherit = 'account.bank.statement'

    l10n_ua_source_type = fields.Selection([
        ('file', 'File import'),
        ('api', 'API'),
        ('manual', 'Manual'),
    ], string='Import Source', help='Тип джерела, з якого сформовано виписку.')
    l10n_ua_source_ref = fields.Char(
        string='Source Reference',
        help='Назва файлу або провайдер/endpoint API.')
    l10n_ua_import_date = fields.Datetime(string='Imported At')
    l10n_ua_sync_job_id = fields.Many2one(
        'l10n_ua.bank.sync.job', string='Sync Job', ondelete='set null')
    l10n_ua_balance_verified = fields.Boolean(
        string='Balance from Source',
        help='Баланси отримані з джерела (контроль повноти дійсний). '
             'Якщо вимкнено — кінцевий баланс виведено з рухів (не перевірка).')
    l10n_ua_balance_ok = fields.Boolean(
        string='Balance Continuity OK', compute='_compute_l10n_ua_balance_ok')

    @api.depends('balance_end', 'balance_end_real', 'l10n_ua_balance_verified')
    def _compute_l10n_ua_balance_ok(self):
        # balance_end (обчислюване) = balance_start + Σ рухів;
        # balance_end_real = закриття з джерела. Контроль повноти: вони рівні.
        for stmt in self:
            stmt.l10n_ua_balance_ok = (
                stmt.l10n_ua_balance_verified
                and abs(stmt.balance_end - stmt.balance_end_real) < 0.01)


class AccountBankStatementLine(models.Model):
    """Рядок native-виписки з зовнішнім ідентифікатором для дедупу імпорту.

    Odoo 19 прибрав `unique_import_id`, тож тримаємо власний індексований
    ключ джерела для ідемпотентного повторного імпорту.
    """
    _inherit = 'account.bank.statement.line'

    l10n_ua_import_uid = fields.Char(
        string='Import UID', index=True,
        help='Зовнішній ідентифікатор руху (для дедупу повторного імпорту).')

    l10n_ua_counterpart_account_id = fields.Many2one(
        'account.account', string='Counterpart Account',
        check_company=True, index='btree_not_null',
        domain="[('account_type', 'not in', ('asset_cash', 'liability_credit_card', 'off_balance'))]",
        help='Кореспондентний рахунок для ручного рознесення без вікна звірки '
             '(Community): внесок до статутного капіталу — 46, фіндопомога — 685/377, '
             'комісія банку — 92. Порожньо — сума йде на рахунок невизначених '
             'надходжень журналу.')

    def _prepare_move_line_default_vals(self, counterpart_account_id=None):
        # Рахунок, обраний вручну, замінює suspense-рахунок журналу; core
        # викликає цей метод і при створенні, і при синхронізації проводки.
        if not counterpart_account_id and self.l10n_ua_counterpart_account_id:
            counterpart_account_id = self.l10n_ua_counterpart_account_id.id
        return super()._prepare_move_line_default_vals(counterpart_account_id)

    def _l10n_ua_manual_counterpart_line(self):
        """Єдиний незвірений кор. рядок ручної транзакції (або порожньо)."""
        self.ensure_one()
        _liquidity, suspense, other = self._seek_for_lines()
        if suspense or len(other) != 1 or other.matched_debit_ids or other.matched_credit_ids:
            return self.env['account.move.line']
        return other

    def _synchronize_to_moves(self, changed_fields):
        # core видаляє «інші» рядки й створює кор. рядок заново, що заборонено
        # на проведеній проводці; рядок ручного рознесення оновлюємо на місці.
        if self.env.context.get('skip_account_move_synchronization') or not any(
                field_name in changed_fields for field_name in (
                    'payment_ref', 'amount', 'amount_currency',
                    'foreign_currency_id', 'currency_id', 'partner_id')):
            return super()._synchronize_to_moves(changed_fields)
        manual = self.filtered(lambda st_line: st_line._l10n_ua_manual_counterpart_line())
        super(AccountBankStatementLine, self - manual)._synchronize_to_moves(changed_fields)
        for st_line in manual.with_context(skip_account_move_synchronization=True):
            liquidity_lines, _suspense, other_lines = st_line._seek_for_lines()
            liquidity_vals, counterpart_vals = st_line._prepare_move_line_default_vals()
            journal = st_line.journal_id
            company_currency = journal.company_id.sudo().currency_id
            journal_currency = journal.currency_id if journal.currency_id != company_currency else False
            move_vals = {
                'currency_id': (st_line.foreign_currency_id or journal_currency or company_currency).id,
                'line_ids': [
                    (1, liquidity_lines.id, liquidity_vals),
                    (1, other_lines.id, counterpart_vals),
                ],
            }
            if st_line.move_id.partner_id != st_line.partner_id:
                move_vals['partner_id'] = st_line.partner_id.id
            st_line.move_id.with_context(skip_readonly_check=True).write(move_vals)

    def action_open_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
        }

    def write(self, vals):
        if 'l10n_ua_counterpart_account_id' in vals:
            for st_line in self:
                _liquidity, suspense, other = st_line._seek_for_lines()
                if (suspense | other).filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids):
                    raise UserError(_(
                        "Transaction \"%s\" is already reconciled. Undo the reconciliation "
                        "before changing the counterpart account.", st_line.display_name))
        res = super().write(vals)
        if 'l10n_ua_counterpart_account_id' in vals:
            # core перебудовує проводку лише при зміні суми/партнера/призначення
            self._synchronize_to_moves({'amount'})
        return res
