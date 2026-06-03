"""Резерв відпусток — П(С)БО 26 «Виплати працівникам», ст. 23.4 ПКУ."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrVacationReserve(models.Model):
    _name = 'hr.vacation.reserve'
    _description = 'Резерв відпусток (документ)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_end desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Номер',
        default=lambda self: _('Нова'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    period_start = fields.Date(
        string='Початок періоду',
        required=True,
        tracking=True,
    )
    period_end = fields.Date(
        string='Кінець періоду',
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('confirmed', 'Підтверджено'),
            ('cancelled', 'Скасовано'),
        ],
        default='draft',
        tracking=True,
        copy=False,
    )

    # --- Бухгалтерія ---
    journal_id = fields.Many2one(
        'account.journal',
        string='Журнал',
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        check_company=True,
    )
    reserve_account_id = fields.Many2one(
        'account.account',
        string='Рахунок резерву (471)',
        domain="[('company_ids', 'in', company_id)]",
        check_company=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Бухгалтерська проводка',
        readonly=True,
        copy=False,
        check_company=True,
    )

    # --- Рядки ---
    line_ids = fields.One2many(
        'hr.vacation.reserve.line',
        'reserve_id',
        string='Рядки',
        copy=False,
    )
    line_count = fields.Integer(
        compute='_compute_summary',
        store=True,
    )
    total_amount = fields.Monetary(
        compute='_compute_summary',
        store=True,
        currency_field='currency_id',
    )

    note = fields.Text(string='Примітки')

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
    )

    @api.depends('line_ids.amount')
    def _compute_summary(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('Нова'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.vacation.reserve'
                ) or _('Нова')
            # Defaults from company
            company = self.env['res.company'].browse(
                vals.get('company_id') or self.env.company.id)
            if not vals.get('journal_id') and company.vacation_reserve_journal_id:
                vals['journal_id'] = company.vacation_reserve_journal_id.id
            if not vals.get('reserve_account_id') and company.vacation_reserve_account_id:
                vals['reserve_account_id'] = company.vacation_reserve_account_id.id
        return super().create(vals_list)

    # --- Дії ---

    def action_fill_lines(self):
        """Заповнити рядки активними працівниками компанії."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Заповнити рядки можна лише з чернетки.'))
        Employee = self.env['hr.employee']
        Line = self.env['hr.vacation.reserve.line']
        existing = self.line_ids.mapped('employee_id').ids
        domain = [
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('id', 'not in', existing),
        ]
        employees = Employee.search(domain)
        for emp in employees:
            Line.create({
                'reserve_id': self.id,
                'employee_id': emp.id,
            })
        return True

    def action_confirm(self):
        """Підтвердити: створити проводку Дт expense / Кт 471."""
        if self.ids:
            self.env.cr.execute(
                'SELECT id FROM hr_vacation_reserve WHERE id IN %s FOR UPDATE',
                (tuple(self.ids),),
            )
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Підтвердити можна лише з чернетки.'))
            if not rec.line_ids:
                raise UserError(_('Додайте хоча б один рядок.'))
            rec._validate_accounts()
            rec._create_account_move()
            rec.state = 'confirmed'
        return True

    def action_cancel(self):
        """Скасувати: спершу скасувати проводку."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Скасувати можна лише підтверджений документ.'))
            if rec.move_id:
                if rec.move_id.state == 'posted':
                    rec.move_id.button_draft()
                rec.move_id.button_cancel()
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('У чернетку можна повернути лише скасовану.'))
            rec.state = 'draft'
        return True

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            return False
        return {
            'name': _('Проводка резерву відпусток'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    def _validate_accounts(self):
        self.ensure_one()
        missing = []
        if not self.journal_id:
            missing.append(_('Журнал'))
        if not self.reserve_account_id:
            missing.append(_('Рахунок резерву (471)'))
        lines_no_account = self.line_ids.filtered(lambda l: not l.expense_account_id)
        if lines_no_account:
            employees = lines_no_account.mapped('employee_id.display_name')
            raise UserError(_(
                'Не задано рахунок витрат для працівників: %s. '
                'Налаштуйте на hr.job, hr.employee або рахунок за замовч. на компанії.'
            ) % ', '.join(employees))
        if missing:
            raise UserError(_(
                'Не заповнено: %s'
            ) % ', '.join(missing))

    def _create_account_move(self):
        """Дт expense_account_id (за функцією) / Кт 471 для кожного рядка."""
        self.ensure_one()
        move_lines = []
        ref = _('Резерв відпусток %s (%s — %s)') % (
            self.name, self.period_start, self.period_end)

        # Group by expense account to reduce line count
        by_account = {}
        for line in self.line_ids:
            if not line.amount:
                continue
            acc = line.expense_account_id
            by_account.setdefault(acc.id, 0.0)
            by_account[acc.id] += line.amount
        for acc_id, total in by_account.items():
            move_lines.append((0, 0, {
                'account_id': acc_id,
                'name': _('Резерв відпусток %s') % self.name,
                'debit': total,
                'credit': 0.0,
            }))
        total = sum(by_account.values())
        if total:
            move_lines.append((0, 0, {
                'account_id': self.reserve_account_id.id,
                'name': _('Резерв відпусток %s') % self.name,
                'debit': 0.0,
                'credit': total,
            }))
        if not move_lines:
            return

        move = self.env['account.move'].create({
            'journal_id': self.journal_id.id,
            'date': self.period_end,
            'ref': ref,
            'company_id': self.company_id.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.move_id = move

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_(
                    'Не можна видалити підтверджений документ резерву. '
                    'Спочатку скасуйте його.'
                ))
        return super().unlink()

    # --- Cron ---

    @api.model
    def _cron_accrue_vacation_reserve(self):
        """Місячне нарахування резерву відпусток для кожної компанії
        з налаштованим автоматичним нарахуванням.
        """
        today = fields.Date.context_today(self)
        # Period is the previous month/quarter
        for company in self.env['res.company'].search([
            ('vacation_reserve_journal_id', '!=', False),
            ('vacation_reserve_account_id', '!=', False),
        ]):
            freq = company.vacation_reserve_frequency or 'monthly'
            if freq == 'monthly':
                period_start = (today.replace(day=1) - relativedelta(months=1))
                period_end = today.replace(day=1) - relativedelta(days=1)
            else:  # quarterly
                quarter_start_month = ((today.month - 1) // 3) * 3 + 1
                period_start = (today.replace(
                    day=1, month=quarter_start_month) - relativedelta(months=3))
                period_end = today.replace(
                    day=1, month=quarter_start_month) - relativedelta(days=1)

            # Skip if already exists
            existing = self.search([
                ('company_id', '=', company.id),
                ('period_start', '=', period_start),
                ('period_end', '=', period_end),
            ], limit=1)
            if existing:
                continue

            rec = self.with_company(company).create({
                'company_id': company.id,
                'period_start': period_start,
                'period_end': period_end,
            })
            rec.action_fill_lines()
            try:
                rec.action_confirm()
            except UserError:
                # Залишити чернеткою якщо немає рахунків — користувач
                # розбереться вручну
                pass


class HrVacationReserveLine(models.Model):
    _name = 'hr.vacation.reserve.line'
    _description = 'Рядок резерву відпусток'
    _order = 'reserve_id, employee_id'
    _check_company_auto = True

    reserve_id = fields.Many2one(
        'hr.vacation.reserve',
        string='Документ',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='reserve_id.company_id',
        store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Працівник',
        required=True,
        domain="[('company_id', '=?', company_id), ('active', '=', True)]",
        check_company=True,
    )
    days_accrued = fields.Float(
        string='Дні нараховано',
        compute='_compute_days_accrued',
        store=True,
        readonly=False,
        precompute=True,
        help='Дні відпустки, нараховані за період',
    )
    daily_average = fields.Float(
        string='Середньоденний',
        compute='_compute_daily_average',
        store=True,
        readonly=False,
        precompute=True,
        help='Середньоденний заробіток для розрахунку резерву',
        digits='Payroll',
    )
    amount = fields.Monetary(
        string='Сума резерву',
        compute='_compute_amount',
        store=True,
        readonly=False,
        precompute=True,
        currency_field='currency_id',
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Рахунок витрат',
        compute='_compute_expense_account',
        store=True,
        readonly=False,
        precompute=True,
        check_company=True,
        domain="[('company_ids', 'in', company_id)]",
    )

    state = fields.Selection(
        related='reserve_id.state',
        store=True,
    )
    currency_id = fields.Many2one(
        related='reserve_id.currency_id',
    )

    @api.depends('employee_id', 'reserve_id.period_start', 'reserve_id.period_end')
    def _compute_days_accrued(self):
        """Дні відпустки за період = (річна норма × днів періоду) / 365."""
        for line in self:
            if not line.employee_id or not line.reserve_id.period_start \
                    or not line.reserve_id.period_end:
                line.days_accrued = 0.0
                continue
            annual_days = line.company_id.vacation_reserve_annual_days or 24.0
            period_days = (line.reserve_id.period_end
                           - line.reserve_id.period_start).days + 1
            line.days_accrued = round(annual_days * period_days / 365.0, 2)

    @api.depends('employee_id', 'reserve_id.period_end')
    def _compute_daily_average(self):
        """Середньоденний заробіток = sum(payslip.net за 12 місяців до кінця періоду) / (12 × 29.3)."""
        Payslip = self.env['hr.payslip']
        for line in self:
            if not line.employee_id or not line.reserve_id.period_end:
                line.daily_average = 0.0
                continue
            period_end = line.reserve_id.period_end
            period_start = period_end - relativedelta(months=12)
            payslips = Payslip.search([
                ('employee_id', '=', line.employee_id.id),
                ('state', 'in', ['done', 'paid']),
                ('date_from', '>=', period_start),
                ('date_to', '<=', period_end),
            ])
            if not payslips:
                # Fallback to contract wage
                contract = line.employee_id.version_id
                wage = contract.wage if contract else 0.0
                line.daily_average = round(wage / 29.3, 2)
                continue
            total = sum(payslips.mapped('total_net') or [0.0])
            line.daily_average = round(total / (12 * 29.3), 2)

    @api.depends('days_accrued', 'daily_average')
    def _compute_amount(self):
        for line in self:
            currency = line.currency_id
            raw = line.days_accrued * line.daily_average
            line.amount = currency.round(raw) if currency else round(raw, 2)

    @api.depends('employee_id', 'employee_id.vacation_reserve_expense_account_id',
                 'employee_id.job_id.vacation_reserve_expense_account_id',
                 'company_id.vacation_reserve_default_expense_account_id')
    def _compute_expense_account(self):
        for line in self:
            if not line.employee_id:
                line.expense_account_id = False
                continue
            line.expense_account_id = line.employee_id._get_vacation_reserve_expense_account()
