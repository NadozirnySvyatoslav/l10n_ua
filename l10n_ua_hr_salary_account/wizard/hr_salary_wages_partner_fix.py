"""Майстер: партнер-працівник на 661/685 у старих проводках ЗП (ADR 0003).

До #592 рядки 661/685 у проводках по зарплаті не мали партнера. У режимі
«проводка на листок» працівник однозначний, тож майстер лише проставляє
партнера (суми не змінюються). У режимі «зведена проводка на пакет» був один
рядок на весь пакет; його можна розбити лише сторно і новою проводкою тією
самою датою, тепер з рядком на працівника.

Майстер свідомо НЕ чіпає закриті періоди (дата блокування), захешовані
проводки і проводки зі звіреними рядками. Спершу — попередній перегляд,
потім застосування; результат пишеться в чатер листка/пакета.
"""

from odoo import fields, models
from odoo.exceptions import UserError


class _Mismatch(Exception):
    """Нова зведена проводка не збігається зі старою по рахунках."""


class HrSalaryWagesPartnerFix(models.TransientModel):
    _name = 'hr.salary.wages.partner.fix'
    _description = 'Партнер-працівник на 661/685 у старих проводках ЗП'

    company_id = fields.Many2one(
        'res.company', string='Компанія', required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [('id', 'in', self.env.companies.ids)],
    )
    date_from = fields.Date(string='Проводки з', required=True)
    date_to = fields.Date(
        string='Проводки по', required=True,
        default=fields.Date.context_today,
    )
    state = fields.Selection(
        [('draft', 'Параметри'), ('preview', 'Перегляд'), ('done', 'Готово')],
        default='draft', required=True,
    )
    summary = fields.Text(string='Результат', readonly=True)

    # ------------------------------------------------------------------
    # Пошук кандидатів
    # ------------------------------------------------------------------

    def _get_config(self):
        self.ensure_one()
        config = self.env['hr.salary.account.config'].search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not config:
            raise UserError(
                'Для компанії "%s" не налаштовано рахунки зарплати.'
                % self.company_id.name)
        config._validate_accounts()
        return config

    def _wages_accounts(self, config):
        return (config.wages_payable_account_id
                | config.other_payable_account_id)

    def _legacy_lines(self, moves, accounts):
        return moves.line_ids.filtered(
            lambda l: l.account_id in accounts and not l.partner_id)

    def _find_candidates(self, config):
        """Листки і пакети, чиї проводки мають 661/685 без партнера."""
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError('Дата «з» пізніша за дату «по».')
        accounts = self._wages_accounts(config)
        lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company_id.id),
            ('account_id', 'in', accounts.ids),
            ('partner_id', '=', False),
            ('parent_state', 'in', ('draft', 'posted')),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        moves = lines.move_id
        slips = self.env['hr.payslip'].search(
            [('move_id', 'in', moves.ids)], order='date_to, id')
        runs = self.env['hr.payslip.run'].search(
            [('move_id', 'in', moves.ids)], order='date_end, id')
        return accounts, slips, runs

    def _lock_reason(self, move):
        violated = move.company_id._get_violated_lock_dates(
            move.date, False, move.journal_id)
        if violated:
            lock_date = max(d for d, _name in violated)
            return 'закритий період (дата блокування %s)' % lock_date
        return False

    # ------------------------------------------------------------------
    # Обробка одного листка / пакета
    # ------------------------------------------------------------------

    def _fix_slip(self, slip, accounts):
        """Проставити партнера на 661/685 у проводці листка."""
        move = slip.move_id
        reason = self._lock_reason(move)
        if not reason and move.inalterable_hash:
            reason = 'проводка захешована, партнера змінити не можна'
        if reason:
            return False, reason
        try:
            partner = slip._l10n_ua_wages_partner()
        except UserError as e:
            return False, str(e)
        lines = self._legacy_lines(move, accounts)
        lines.write({'partner_id': partner.id})
        return True, 'партнер %s на %d рядках' % (partner.name, len(lines))

    @staticmethod
    def _account_totals(move):
        """Сальдо по (рахунок, аналітика) без урахування партнера."""
        totals = {}
        for line in move.line_ids:
            dist = line.analytic_distribution or {}
            key = (line.account_id.id,
                   tuple(sorted((str(k), v) for k, v in dist.items())))
            totals[key] = totals.get(key, 0.0) + line.balance
        return {k: round(v, 2) for k, v in totals.items() if round(v, 2)}

    def _fix_run(self, run, config, accounts):
        """Сторно зведеної проводки пакета і нова — з рядком на працівника."""
        old = run.move_id
        reason = self._lock_reason(old)
        if not reason and old.date != run.date_end:
            reason = ('дата проводки %s не збігається з кінцем пакета %s'
                      % (old.date, run.date_end))
        if not reason and old.line_ids.filtered(
                lambda l: l.matched_debit_ids or l.matched_credit_ids):
            reason = 'у проводці є звірені рядки, спершу розвʼяжіть звірку'
        if reason:
            return False, reason
        try:
            for slip in run.slip_ids.filtered(lambda s: s.state == 'done'):
                slip._l10n_ua_wages_partner()
        except UserError as e:
            return False, str(e)

        old_totals = self._account_totals(old)
        old_name = old.name
        try:
            with self.env.cr.savepoint():
                if old.state == 'posted':
                    old._reverse_moves(
                        default_values_list=[{
                            'ref': 'Сторно: %s' % old.ref,
                            'date': old.date,
                        }],
                        cancel=True,
                    )
                else:
                    old.unlink()
                run.move_id = False
                run._create_consolidated_move(config)
                new = run.move_id
                if not new or self._account_totals(new) != old_totals:
                    raise _Mismatch()
        except _Mismatch:
            return False, ('нова проводка не збігається зі старою по '
                           'рахунках/сумах (змінились налаштування '
                           'рахунків?), пакет не змінено')
        lines = self._legacy_lines(new, accounts)
        if lines:
            return False, 'після перепроведення лишились рядки без партнера'
        return True, '%s → %s' % (old_name, new.name)

    def _process(self, config, accounts, slips, runs):
        """Повертає список (запис, успіх, опис)."""
        results = []
        for slip in slips:
            ok, msg = self._fix_slip(slip, accounts)
            results.append((slip, ok, msg))
        for run in runs:
            ok, msg = self._fix_run(run, config, accounts)
            results.append((run, ok, msg))
        return results

    def _header(self, slips, runs, accounts):
        lines = self._legacy_lines(slips.move_id | runs.move_id, accounts)
        return ('Знайдено: листків %d, пакетів %d, рядків 661/685 без '
                'партнера %d, на суму %.2f.' % (
                    len(slips), len(runs), len(lines),
                    sum(abs(l.balance) for l in lines)))

    @staticmethod
    def _report(header, results, done):
        """results: [(назва, успіх, опис)]."""
        n_ok = len([r for r in results if r[1]])
        text = [header, '%s: %d, %s: %d.' % (
            'Виправлено' if done else 'Можна виправити', n_ok,
            'пропущено' if done else 'буде пропущено',
            len(results) - n_ok), '']
        text += ['- %s %s: %s' % ('OK' if ok else 'ПРОПУЩЕНО', name, msg)
                 for name, ok, msg in results]
        if not results:
            text.append('Проводок без партнера на 661/685 у цьому '
                        'періоді немає.')
        return '\n'.join(text)

    # ------------------------------------------------------------------
    # Дії
    # ------------------------------------------------------------------

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_preview(self):
        """Прогнати виправлення в savepoint і відкотити: що саме зміниться."""
        self.ensure_one()
        self = self.with_company(self.company_id)
        config = self._get_config()
        accounts, slips, runs = self._find_candidates(config)
        header = self._header(slips, runs, accounts)
        with self.env.cr.savepoint() as sp:
            results = [(r.display_name, ok, msg) for r, ok, msg
                       in self._process(config, accounts, slips, runs)]
            sp.close(rollback=True)
        self.write({'state': 'preview',
                    'summary': self._report(header, results, False)})
        return self._reopen()

    def action_apply(self):
        self.ensure_one()
        self = self.with_company(self.company_id)
        config = self._get_config()
        accounts, slips, runs = self._find_candidates(config)
        header = self._header(slips, runs, accounts)
        results = self._process(config, accounts, slips, runs)
        for rec, ok, msg in results:
            if ok:
                rec.message_post(body=(
                    'Партнер-працівник на 661/685 у проводці (майстер, '
                    'ADR 0003): %s' % msg))
        self.write({'state': 'done', 'summary': self._report(
            header, [(r.display_name, ok, msg) for r, ok, msg in results],
            True)})
        return self._reopen()

    def action_back(self):
        self.write({'state': 'draft', 'summary': False})
        return self._reopen()
