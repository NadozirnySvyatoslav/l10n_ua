from odoo import _, api, fields, models
from odoo.exceptions import UserError


class L10nUaOsv(models.Model):
    _name = 'l10n_ua.osv'
    _description = 'Trial Balance / OSV (Оборотно-сальдова відомість)'
    _order = 'period_start desc'

    # Типи аналітики рахунку, для яких ОСВ розгортається по контрагентах.
    _EXPAND_ANALYTICS = ('partner', 'employee')

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    period_start = fields.Date(
        string='Period Start',
        required=True,
    )
    period_end = fields.Date(
        string='Period End',
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    line_ids = fields.One2many(
        'l10n_ua.osv.line',
        'osv_id',
        string='Lines',
    )
    summary_line_ids = fields.One2many(
        'l10n_ua.osv.line',
        'osv_id',
        string='Account Lines',
        domain=[('is_detail', '=', False)],
    )
    detail_line_ids = fields.One2many(
        'l10n_ua.osv.line',
        'osv_id',
        string='Partner Breakdown',
        domain=[('is_detail', '=', True)],
    )
    expand_partners = fields.Boolean(
        string='Expand by Partners',
        help='Для рахунків з аналітикою по контрагентах або працівниках '
             '(361, 631, 661, 68х тощо — поле «Тип аналітики» рахунку) '
             'показати розгортку по кожному контрагенту і розгорнуте сальдо: '
             'дебетове і кредитове сальдо рахунку — окремо, як суми сальдо '
             'контрагентів. Решта рахунків — як у синтетичній ОСВ.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
        ],
        string='State',
        default='draft',
    )
    osv_type = fields.Selection(
        selection=[
            ('synthetic', 'Synthetic'),
            ('analytic', 'Analytic'),
            ('subconto', 'By Subconto'),
        ],
        string='Type',
        default='synthetic',
    )
    subconto_type_id = fields.Many2one(
        'l10n_ua.subconto.type',
        string='Subconto Type',
        help='Вид субконто для розбивки (лише для типу «By Subconto»).',
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        help='Обмежити ОСВ одним рахунком (опційно).',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
    )

    @api.depends('period_start', 'period_end', 'osv_type')
    def _compute_name(self):
        for record in self:
            selections = dict(self._fields['osv_type']._description_selection(self.env))
            type_name = selections.get(record.osv_type, '')
            if record.period_start:
                # Odoo sometimes fails to load complex string translations in code without a full restart.
                # Splitting it makes it more robust.
                osv_prefix = _('OSV')
                if osv_prefix == 'OSV' and self.env.lang == 'uk_UA':
                    osv_prefix = 'ОСВ'
                record.name = f"{osv_prefix} {type_name} ({record.period_start} - {record.period_end})"
            else:
                new_str = _('New')
                if new_str == 'New' and self.env.lang == 'uk_UA':
                    new_str = 'Новий'
                record.name = new_str

    def action_compute(self):
        """Compute OSV lines from posted account moves.

        Builds opening balance / period turnover / closing balance per account
        (and per partner for analytic OSV) from ``account.move.line``.
        """
        self.ensure_one()
        if not self.period_start or not self.period_end:
            raise UserError(_('Please set the period start and end dates.'))
        if self.period_end < self.period_start:
            raise UserError(_('Period end cannot be earlier than period start.'))

        self.line_ids.unlink()

        AML = self.env['account.move.line']
        currency = self.company_id.currency_id

        # Вимір розбивки: None (синтетична) / 'partner_id' (аналітична) /
        # quick-поле субконто (розбивка по обраному виду субконто).
        dim_field = None
        expand = self.osv_type == 'synthetic' and self.expand_partners
        if self.osv_type == 'analytic' or expand:
            dim_field = 'partner_id'
        elif self.osv_type == 'subconto':
            if not self.subconto_type_id:
                raise UserError(_('Оберіть вид субконто для розбивки.'))
            dim_field = AML._subconto_quick_fields_map().get(
                self.subconto_type_id.model_name)
            if not dim_field:
                raise UserError(_(
                    'Для виду субконто «%s» немає швидкого поля для групування. '
                    'Додайте bridge-модуль (напр. l10n_ua_account_subconto_hr).'
                ) % self.subconto_type_id.name)

        groupby = ['account_id'] + ([dim_field] if dim_field else [])
        empty_rec = self.env['res.partner']

        base_domain = [
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]
        if self.account_id:
            base_domain.append(('account_id', '=', self.account_id.id))
        if self.osv_type == 'subconto':
            # Лише рядки, що мають значення обраного субконто.
            base_domain.append((dim_field, '!=', False))

        # key -> accumulator
        data = {}

        def bucket(account, dim):
            key = (account.id, dim.id if dim else False)
            return data.setdefault(key, {
                'account': account,
                'dim': dim,
                'opening': 0.0,
                'turnover_debit': 0.0,
                'turnover_credit': 0.0,
            })

        # Opening balance: net of everything posted before the period start.
        opening_rows = AML._read_group(
            base_domain + [('date', '<', self.period_start)],
            groupby,
            ['balance:sum'],
        )
        for row in opening_rows:
            account = row[0]
            dim = row[1] if dim_field else empty_rec
            bucket(account, dim)['opening'] += row[-1] or 0.0

        # Turnover: debit/credit movements within the period.
        turnover_rows = AML._read_group(
            base_domain + [
                ('date', '>=', self.period_start),
                ('date', '<=', self.period_end),
            ],
            groupby,
            ['debit:sum', 'credit:sum'],
        )
        for row in turnover_rows:
            account = row[0]
            dim = row[1] if dim_field else empty_rec
            acc = bucket(account, dim)
            acc['turnover_debit'] += row[-2] or 0.0
            acc['turnover_credit'] += row[-1] or 0.0

        if expand:
            self.line_ids = self._expanded_lines(data.values(), currency)
            return True

        is_partner_dim = dim_field == 'partner_id'
        is_subconto = self.osv_type == 'subconto'
        lines = []
        for acc in data.values():
            opening = acc['opening']
            turnover_debit = acc['turnover_debit']
            turnover_credit = acc['turnover_credit']
            closing = opening + turnover_debit - turnover_credit
            dim = acc['dim']

            # Skip fully empty accounts (e.g. equal debit/credit netting to zero).
            if (currency.is_zero(opening)
                    and currency.is_zero(turnover_debit)
                    and currency.is_zero(turnover_credit)):
                continue

            lines.append((0, 0, {
                'account_id': acc['account'].id,
                'partner_id': dim.id if (is_partner_dim and dim) else False,
                'subconto_label': dim.display_name if (is_subconto and dim) else '',
                'opening_debit': opening if opening > 0 else 0.0,
                'opening_credit': -opening if opening < 0 else 0.0,
                'turnover_debit': turnover_debit,
                'turnover_credit': turnover_credit,
                'closing_debit': closing if closing > 0 else 0.0,
                'closing_credit': -closing if closing < 0 else 0.0,
            }))

        self.line_ids = lines
        return True

    @staticmethod
    def _balance_vals(opening, turnover_debit, turnover_credit):
        """Згорнуте сальдо одного рядка: нетто на початок/кінець у Дт або Кт."""
        closing = opening + turnover_debit - turnover_credit
        return {
            'opening_debit': opening if opening > 0 else 0.0,
            'opening_credit': -opening if opening < 0 else 0.0,
            'turnover_debit': turnover_debit,
            'turnover_credit': turnover_credit,
            'closing_debit': closing if closing > 0 else 0.0,
            'closing_credit': -closing if closing < 0 else 0.0,
        }

    def _expanded_lines(self, buckets, currency):
        """Синтетична ОСВ з розгорткою по контрагентах (#588).

        ``buckets`` — накопичувачі (рахунок, контрагент). Рахунки з аналітикою
        по контрагентах/працівниках дають рядок рахунку з розгорнутим сальдо
        (Дт і Кт — суми сальдо контрагентів окремо) і рядки-розгортку
        ``is_detail``; решта рахунків — один рядок зі згорнутим сальдо, як у
        звичайній синтетичній ОСВ.
        """
        money = ('opening_debit', 'opening_credit', 'turnover_debit',
                 'turnover_credit', 'closing_debit', 'closing_credit')
        by_account = {}
        for acc in buckets:
            if (currency.is_zero(acc['opening'])
                    and currency.is_zero(acc['turnover_debit'])
                    and currency.is_zero(acc['turnover_credit'])):
                continue
            by_account.setdefault(acc['account'], []).append(acc)

        lines = []
        for account, rows in by_account.items():
            if account.ua_analytics_type not in self._EXPAND_ANALYTICS:
                lines.append((0, 0, dict(self._balance_vals(
                    sum(r['opening'] for r in rows),
                    sum(r['turnover_debit'] for r in rows),
                    sum(r['turnover_credit'] for r in rows),
                ), account_id=account.id)))
                continue

            summary = dict.fromkeys(money, 0.0)
            details = []
            for row in sorted(rows, key=lambda r: r['dim'].display_name or ''):
                vals = self._balance_vals(
                    row['opening'], row['turnover_debit'], row['turnover_credit'])
                for field in money:
                    summary[field] += vals[field]
                details.append((0, 0, dict(
                    vals,
                    account_id=account.id,
                    partner_id=row['dim'].id or False,
                    is_detail=True,
                )))
            lines.append((0, 0, dict(summary, account_id=account.id)))
            lines += details
        return lines

    def action_open_lines(self):
        """Рядки ОСВ окремим списком, згруповані по рахунках — для експорту."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'l10n_ua.osv.line',
            'view_mode': 'list',
            'views': [(self.env.ref(
                'l10n_ua_account_base.l10n_ua_osv_line_view_list').id, 'list')],
            'domain': [('osv_id', '=', self.id)],
        }

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_draft(self):
        self.write({'state': 'draft'})


class L10nUaOsvLine(models.Model):
    _name = 'l10n_ua.osv.line'
    _description = 'OSV Line'
    _order = 'account_id, is_detail, partner_id, id'

    is_detail = fields.Boolean(
        string='Breakdown Row',
        default=False,
        help='Рядок розгортки рахунку по контрагенту (ОСВ з розгорткою).',
    )
    osv_id = fields.Many2one(
        'l10n_ua.osv',
        string='OSV',
        required=True,
        ondelete='cascade',
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
    )
    subconto_label = fields.Char(
        string='Subconto',
        help='Значення субконто (для ОСВ по субконто).',
    )
    opening_debit = fields.Monetary(
        string='Opening Debit',
        currency_field='currency_id',
    )
    opening_credit = fields.Monetary(
        string='Opening Credit',
        currency_field='currency_id',
    )
    turnover_debit = fields.Monetary(
        string='Turnover Debit',
        currency_field='currency_id',
    )
    turnover_credit = fields.Monetary(
        string='Turnover Credit',
        currency_field='currency_id',
    )
    closing_debit = fields.Monetary(
        string='Closing Debit',
        currency_field='currency_id',
    )
    closing_credit = fields.Monetary(
        string='Closing Credit',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='osv_id.currency_id',
    )
