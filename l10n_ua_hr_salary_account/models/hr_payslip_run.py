import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
        help='Зведена бухгалтерська проводка по зарплаті за період',
    )

    # ------------------------------------------------------------------
    # State overrides
    # ------------------------------------------------------------------

    def action_close(self):
        res = super().action_close()
        for run in self:
            if run.move_id:
                continue
            config = self.env['hr.salary.account.config'].search(
                [('company_id', '=', run.company_id.id)], limit=1,
            )
            if config and config.entry_granularity == 'per_batch':
                run._create_consolidated_move(config)
        return res

    def action_draft(self):
        for run in self:
            run._reverse_account_move()
        return super().action_draft()

    # ------------------------------------------------------------------
    # Consolidated journal entry
    # ------------------------------------------------------------------

    @staticmethod
    def _analytic_key(dist):
        """Hashable grouping key for an analytic distribution dict."""
        if not dist:
            return ()
        return tuple(sorted((str(k), v) for k, v in dist.items()))

    def _create_consolidated_move(self, config):
        """Create one consolidated journal entry for the entire batch."""
        self.ensure_one()
        if self.move_id:
            return

        config._validate_accounts()

        done_slips = self.slip_ids.filtered(lambda s: s.state == 'done')
        if not done_slips:
            _logger.warning('No done payslips in batch %s', self.name)
            return

        # Group by expense account + analytic distribution (department/project)
        expense_totals = {}  # {(account_id, dist_key): {...}}
        total_pdfo = 0.0
        total_military = 0.0
        total_other = 0.0
        # 661/685 go one line per employee (partner), so the trial balance
        # can show 661 per employee (#578). {partner: {...}}
        per_partner = {}

        for slip in done_slips:
            partner = slip._l10n_ua_wages_partner()
            emp = per_partner.setdefault(partner, {
                'gross': 0.0, 'pdfo': 0.0, 'military': 0.0, 'other': 0.0})
            emp['gross'] += slip.gross_salary
            emp['pdfo'] += slip.pdfo_amount
            emp['military'] += slip.military_tax_amount
            emp['other'] += slip._l10n_ua_other_deductions_to_post()
            expense_account = slip._get_expense_account(config)
            dist = slip._get_salary_analytic_distribution()
            key = (expense_account.id, self._analytic_key(dist))
            if key not in expense_totals:
                expense_totals[key] = {
                    'account': expense_account,
                    'distribution': dist,
                    'gross': 0.0,
                    'esv': 0.0,
                }
            expense_totals[key]['gross'] += slip.gross_salary
            expense_totals[key]['esv'] += slip.esv_amount
            total_pdfo += slip.pdfo_amount
            total_military += slip.military_tax_amount
            total_other += slip._l10n_ua_other_deductions_to_post()

        lines = []

        # --- Debit: expense accounts (grouped by department + analytics) ---
        for data in expense_totals.values():
            acc = data['account']
            dist = data['distribution'] or False
            gross = round(data['gross'], 2)
            esv = round(data['esv'], 2)
            if gross:
                lines.append({
                    'name': 'Нарахування ЗП — %s' % acc.display_name,
                    'account_id': acc.id,
                    'debit': gross,
                    'credit': 0.0,
                    'analytic_distribution': dist,
                })
            if esv:
                lines.append({
                    'name': 'Нарахування ЄСВ — %s' % acc.display_name,
                    'account_id': acc.id,
                    'debit': esv,
                    'credit': 0.0,
                    'analytic_distribution': dist,
                })

        def wages_lines(name, key, side, account):
            """One 661/685 line per employee for the given amount."""
            for partner, emp in per_partner.items():
                amount = round(emp[key], 2)
                if not amount:
                    continue
                lines.append({
                    'name': '%s: %s' % (name, partner.name),
                    'account_id': account.id,
                    'partner_id': partner.id,
                    'debit': amount if side == 'debit' else 0.0,
                    'credit': amount if side == 'credit' else 0.0,
                })

        # --- Credit: wages payable (gross), per employee ---
        wages_lines('Заробітна плата до виплати', 'gross', 'credit',
                    config.wages_payable_account_id)

        # --- Credit: ESV payable ---
        total_esv = round(sum(d['esv'] for d in expense_totals.values()), 2)
        if total_esv:
            lines.append({
                'name': 'ЄСВ нараховано',
                'account_id': config.esv_payable_account_id.id,
                'debit': 0.0,
                'credit': total_esv,
            })

        # --- PDFO withholding: Дт 661 / Кт 6411 ---
        total_pdfo = round(total_pdfo, 2)
        if total_pdfo:
            wages_lines('ПДФО утримано', 'pdfo', 'debit',
                        config.wages_payable_account_id)
            lines.append({
                'name': 'ПДФО утримано',
                'account_id': config.pdfo_payable_account_id.id,
                'debit': 0.0,
                'credit': total_pdfo,
            })

        # --- Military tax: Дт 661 / Кт 6415 ---
        total_military = round(total_military, 2)
        if total_military:
            wages_lines('Військовий збір утримано', 'military', 'debit',
                        config.wages_payable_account_id)
            lines.append({
                'name': 'Військовий збір утримано',
                'account_id': config.military_tax_payable_account_id.id,
                'debit': 0.0,
                'credit': total_military,
            })

        # --- Other deductions: Дт 661 / Кт 685 ---
        total_other = round(total_other, 2)
        if total_other and config.other_payable_account_id:
            wages_lines('Інші утримання', 'other', 'debit',
                        config.wages_payable_account_id)
            wages_lines('Інші утримання', 'other', 'credit',
                        config.other_payable_account_id)

        if not lines:
            return

        # Balance check
        total_debit = sum(l['debit'] for l in lines)
        total_credit = sum(l['credit'] for l in lines)
        if abs(total_debit - total_credit) > 0.01:
            raise UserError(
                'Незбалансована зведена проводка для %s: дебет=%.2f, кредит=%.2f'
                % (self.name, total_debit, total_credit)
            )

        move = self.env['account.move'].sudo().create({
            'journal_id': config.salary_journal_id.id,
            'date': self.date_end,
            'ref': 'Зарплата: %s' % self.name,
            'company_id': self.company_id.id,
            'line_ids': [(0, 0, line) for line in lines],
        })
        self.move_id = move

        if config.auto_post:
            move.action_post()

    # ------------------------------------------------------------------
    # Reversal
    # ------------------------------------------------------------------

    def _reverse_account_move(self):
        """Reverse or delete the linked journal entry."""
        self.ensure_one()
        if not self.move_id:
            return
        if self.move_id.state == 'posted':
            self.move_id._reverse_moves(
                default_values_list=[{
                    'ref': 'Сторно: %s' % self.move_id.ref,
                }],
                cancel=True,
            )
        else:
            self.move_id.unlink()
        self.move_id = False

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_move(self):
        """Open the related journal entry."""
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
