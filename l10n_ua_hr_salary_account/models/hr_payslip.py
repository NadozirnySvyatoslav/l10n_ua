import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
        help='Бухгалтерська проводка, створена при підтвердженні розрахункового листка',
    )

    # ------------------------------------------------------------------
    # State overrides
    # ------------------------------------------------------------------

    def action_payslip_done(self):
        res = super().action_payslip_done()
        for payslip in self:
            if payslip.move_id:
                continue
            config = self.env['hr.salary.account.config'].search(
                [('company_id', '=', payslip.company_id.id)], limit=1,
            )
            if config and config.entry_granularity == 'per_payslip':
                payslip._create_account_move(config)
        return res

    def action_payslip_cancel(self):
        for payslip in self:
            payslip._reverse_account_move()
        return super().action_payslip_cancel()

    # ------------------------------------------------------------------
    # Journal entry creation
    # ------------------------------------------------------------------

    def _create_account_move(self, config):
        """Create a journal entry for a single payslip."""
        self.ensure_one()
        if self.move_id:
            return

        config._validate_accounts()
        lines = self._prepare_move_lines(config)
        if not lines:
            _logger.warning('No move lines generated for payslip %s', self.name)
            return

        # Sanity check: debit == credit
        total_debit = sum(l['debit'] for l in lines)
        total_credit = sum(l['credit'] for l in lines)
        if abs(total_debit - total_credit) > 0.01:
            raise UserError(
                'Незбалансована проводка для %s: дебет=%.2f, кредит=%.2f'
                % (self.name, total_debit, total_credit)
            )

        move_vals = {
            'journal_id': config.salary_journal_id.id,
            'date': self.date_to,
            'ref': '%s — %s' % (self.name, self.employee_id.name),
            'company_id': self.company_id.id,
            'line_ids': [(0, 0, line) for line in lines],
        }
        move = self.env['account.move'].sudo().create(move_vals)
        self.move_id = move

        if config.auto_post:
            move.action_post()

    def _get_expense_account(self, config):
        """Get expense account: department-specific or default."""
        self.ensure_one()
        dept = self.department_id
        if dept and dept.salary_expense_account_id:
            return dept.salary_expense_account_id
        if config.default_expense_account_id:
            return config.default_expense_account_id
        raise UserError(
            'Не вказано рахунок витрат для підрозділу "%s" '
            'та не налаштовано рахунок за замовчуванням.'
            % (dept.name if dept else '—')
        )

    def _get_salary_analytic_distribution(self):
        """Analytic distribution for expense lines.

        Resolution: version (contract) override → department default → none.
        Returns a distribution dict ({analytic_account_id: percentage}) or False.
        """
        self.ensure_one()
        version = self.version_id
        dist = version.salary_analytic_distribution if version else False
        if not dist:
            dept = self.department_id
            dist = dept.salary_analytic_distribution if dept else False
        return dist or False

    def _l10n_ua_other_deductions_to_post(self):
        """Withholdings to post as Дт 661 / Кт 685.

        ``other_deductions`` also holds the advance deduction (category
        ``advance``): it lowers the net pay, but the advance has already
        debited 661 when it was paid out (Дт 661 Кт 301/311). Posting it
        again through 685 would lower 661 twice and leave a fake debt on
        685 (#574), so the advance is left out here. ``net_salary`` is
        not affected.
        """
        self.ensure_one()
        return sum(
            d.amount for d in self.deduction_ids
            if d.deduction_type_id.category not in ('tax', 'advance')
        )

    def _l10n_ua_wages_partner(self):
        """Partner for the 661/685 lines of this payslip (#578).

        The employee's work contact, so that the trial balance can show
        661/685 per employee and the bank payment can be reconciled with
        the accrual. An employee without a work contact is an error: a
        line without a partner would silently break the breakdown.
        """
        self.ensure_one()
        partner = self.employee_id.work_contact_id
        if not partner:
            raise UserError(
                'У працівника "%s" немає робочого контакту (партнера). '
                'Без нього рядки 661/685 не матимуть розгортки по '
                'працівниках. Відкрийте картку працівника і заповніть '
                'робочий контакт.' % self.employee_id.name
            )
        return partner

    def _prepare_move_lines(self, config):
        """Build list of account.move.line dicts for this payslip."""
        self.ensure_one()
        lines = []
        expense_account = self._get_expense_account(config)
        analytic = self._get_salary_analytic_distribution()
        emp_name = self.employee_id.name
        partner_id = self._l10n_ua_wages_partner().id

        # 1. Salary accrual: Дт expense / Кт 661
        if self.gross_salary:
            lines.append({
                'name': 'Нарахування ЗП: %s' % emp_name,
                'account_id': expense_account.id,
                'debit': round(self.gross_salary, 2),
                'credit': 0.0,
                'analytic_distribution': analytic or False,
            })
            lines.append({
                'name': 'Нарахування ЗП: %s' % emp_name,
                'account_id': config.wages_payable_account_id.id,
                'partner_id': partner_id,
                'debit': 0.0,
                'credit': round(self.gross_salary, 2),
            })

        # 2. ESV accrual: Дт expense / Кт 651
        if self.esv_amount:
            lines.append({
                'name': 'ЄСВ: %s' % emp_name,
                'account_id': expense_account.id,
                'debit': round(self.esv_amount, 2),
                'credit': 0.0,
                'analytic_distribution': analytic or False,
            })
            lines.append({
                'name': 'ЄСВ: %s' % emp_name,
                'account_id': config.esv_payable_account_id.id,
                'debit': 0.0,
                'credit': round(self.esv_amount, 2),
            })

        # 3. PDFO withholding: Дт 661 / Кт 6411
        if self.pdfo_amount:
            lines.append({
                'name': 'ПДФО: %s' % emp_name,
                'account_id': config.wages_payable_account_id.id,
                'partner_id': partner_id,
                'debit': round(self.pdfo_amount, 2),
                'credit': 0.0,
            })
            lines.append({
                'name': 'ПДФО: %s' % emp_name,
                'account_id': config.pdfo_payable_account_id.id,
                'debit': 0.0,
                'credit': round(self.pdfo_amount, 2),
            })

        # 4. Military tax: Дт 661 / Кт 6415
        if self.military_tax_amount:
            lines.append({
                'name': 'Військовий збір: %s' % emp_name,
                'account_id': config.wages_payable_account_id.id,
                'partner_id': partner_id,
                'debit': round(self.military_tax_amount, 2),
                'credit': 0.0,
            })
            lines.append({
                'name': 'Військовий збір: %s' % emp_name,
                'account_id': config.military_tax_payable_account_id.id,
                'debit': 0.0,
                'credit': round(self.military_tax_amount, 2),
            })

        # 5. Other deductions: Дт 661 / Кт 685 (without the advance, #574)
        other = round(self._l10n_ua_other_deductions_to_post(), 2)
        if other and config.other_payable_account_id:
            lines.append({
                'name': 'Інші утримання: %s' % emp_name,
                'account_id': config.wages_payable_account_id.id,
                'partner_id': partner_id,
                'debit': other,
                'credit': 0.0,
            })
            lines.append({
                'name': 'Інші утримання: %s' % emp_name,
                'account_id': config.other_payable_account_id.id,
                'partner_id': partner_id,
                'debit': 0.0,
                'credit': other,
            })

        return lines

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
