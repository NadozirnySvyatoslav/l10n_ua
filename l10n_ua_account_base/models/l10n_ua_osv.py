from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class L10nUaOsv(models.Model):
    _name = 'l10n_ua.osv'
    _description = 'Trial Balance / OSV (Оборотно-сальдова відомість)'
    _order = 'period_start desc'

    # Типи аналітики рахунку, для яких ОСВ розгортається по контрагентах.
    _EXPAND_ANALYTICS = ('partner', 'employee')
    # Тип аналітики рахунку, для якого ОСВ розгортається по номенклатурі.
    _EXPAND_PRODUCT_ANALYTICS = 'product'
    _MONEY_FIELDS = ('opening_debit', 'opening_credit', 'turnover_debit',
                     'turnover_credit', 'closing_debit', 'closing_credit')
    _QTY_FIELDS = ('opening_qty', 'turnover_qty_in', 'turnover_qty_out',
                   'closing_qty')

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
        string='Breakdown',
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
    expand_products = fields.Boolean(
        string='Expand by Products',
        help='Для рахунків з аналітикою по номенклатурі (20х, 22, 26, 28 — '
             'поле «Тип аналітики» рахунку = «By product») показати розгортку '
             'по кожному товару: сальдо й обороти в сумі і в кількості '
             '(кількість — з рядків проводок). Решта рахунків — як у '
             'синтетичній ОСВ.',
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
        expand = self.osv_type == 'synthetic' and (
            self.expand_partners or self.expand_products)
        if self.osv_type == 'analytic':
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

        if expand:
            self.line_ids = self._expanded_lines(
                self._expanded_buckets(base_domain), currency)
            return True

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

    def _expanded_buckets(self, base_domain):
        """Накопичувачі (рахунок, контрагент, товар) для ОСВ з розгорткою.

        Суми — як у синтетичній ОСВ; кількість (``quantity`` рядків проводок)
        — лише для рахунків з аналітикою по номенклатурі, якщо ввімкнено
        розгортку по номенклатурі: дебетові рядки — надходження, кредитові —
        вибуття.
        """
        AML = self.env['account.move.line']
        groupby = ['account_id', 'partner_id', 'product_id']
        before = [('date', '<', self.period_start)]
        period = [('date', '>=', self.period_start),
                  ('date', '<=', self.period_end)]
        data = {}

        def bucket(account, partner, product):
            return data.setdefault((account.id, partner.id, product.id), {
                'account': account,
                'partner': partner,
                'product': product,
                'opening': 0.0,
                'turnover_debit': 0.0,
                'turnover_credit': 0.0,
                'opening_qty': 0.0,
                'turnover_qty_in': 0.0,
                'turnover_qty_out': 0.0,
            })

        for account, partner, product, balance in AML._read_group(
                base_domain + before, groupby, ['balance:sum']):
            bucket(account, partner, product)['opening'] += balance or 0.0
        for account, partner, product, debit, credit in AML._read_group(
                base_domain + period, groupby, ['debit:sum', 'credit:sum']):
            acc = bucket(account, partner, product)
            acc['turnover_debit'] += debit or 0.0
            acc['turnover_credit'] += credit or 0.0

        if self.expand_products:
            qty_domain = base_domain + [
                ('account_id.ua_analytics_type', '=', self._EXPAND_PRODUCT_ANALYTICS)]
            for dates, side, key, sign in (
                    (before, ('debit', '>', 0), 'opening_qty', 1),
                    (before, ('credit', '>', 0), 'opening_qty', -1),
                    (period, ('debit', '>', 0), 'turnover_qty_in', 1),
                    (period, ('credit', '>', 0), 'turnover_qty_out', 1)):
                for account, partner, product, qty in AML._read_group(
                        qty_domain + dates + [side], groupby, ['quantity:sum']):
                    bucket(account, partner, product)[key] += sign * (qty or 0.0)
        return data.values()

    def _expand_dim(self, account):
        """Вимір розгортки рахунку: 'partner' / 'product' / None (без розгортки)."""
        if self.expand_partners and account.ua_analytics_type in self._EXPAND_ANALYTICS:
            return 'partner'
        if (self.expand_products
                and account.ua_analytics_type == self._EXPAND_PRODUCT_ANALYTICS):
            return 'product'
        return None

    def _expanded_lines(self, buckets, currency):
        """Синтетична ОСВ з розгорткою по контрагентах / номенклатурі (#588).

        ``buckets`` — накопичувачі (рахунок, контрагент, товар). Рахунки з
        аналітикою по контрагентах/працівниках (прапорець «по контрагентах»)
        або по номенклатурі (прапорець «по номенклатурі») дають рядок рахунку
        з розгорнутим сальдо (Дт і Кт — суми сальдо розгортки окремо) і
        рядки-розгортку ``is_detail``; для номенклатури — ще й кількість.
        Решта рахунків — один рядок зі згорнутим сальдо, як у звичайній
        синтетичній ОСВ.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit')
        amounts = ('opening', 'turnover_debit', 'turnover_credit')
        qtys = ('opening_qty', 'turnover_qty_in', 'turnover_qty_out')

        # рахунок -> {значення виміру (запис або порожній) -> суми}
        by_account = {}
        for acc in buckets:
            account = acc['account']
            dim = self._expand_dim(account)
            value = acc[dim] if dim else None
            groups = by_account.setdefault(account, {})
            total = groups.setdefault(
                value.id if value is not None else None,
                dict.fromkeys(amounts + qtys, 0.0) |{'value': value})
            for field in amounts + qtys:
                total[field] += acc[field]

        def is_empty(row):
            return (all(currency.is_zero(row[f]) for f in amounts)
                    and all(float_is_zero(row[f], precision_digits=precision)
                            for f in qtys))

        lines = []
        for account in sorted(by_account, key=lambda a: a.code or ''):
            dim = self._expand_dim(account)
            rows = [r for r in by_account[account].values() if not is_empty(r)]
            if not rows:
                continue
            if not dim:
                lines.append((0, 0, dict(self._balance_vals(
                    rows[0]['opening'], rows[0]['turnover_debit'],
                    rows[0]['turnover_credit']), account_id=account.id)))
                continue

            summary = dict.fromkeys(self._MONEY_FIELDS + self._QTY_FIELDS, 0.0)
            details = []
            for row in sorted(rows, key=lambda r: r['value'].display_name or ''):
                vals = self._balance_vals(
                    row['opening'], row['turnover_debit'], row['turnover_credit'])
                if dim == 'product':
                    vals.update(
                        opening_qty=row['opening_qty'],
                        turnover_qty_in=row['turnover_qty_in'],
                        turnover_qty_out=row['turnover_qty_out'],
                        closing_qty=(row['opening_qty'] + row['turnover_qty_in']
                                     - row['turnover_qty_out']),
                    )
                for field, value in vals.items():
                    summary[field] += value
                details.append((0, 0, dict(
                    vals,
                    account_id=account.id,
                    **{f'{dim}_id': row['value'].id or False},
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
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        help='Товар рядка розгортки (ОСВ з розгорткою по номенклатурі).',
    )
    subconto_label = fields.Char(
        string='Subconto',
        help='Значення субконто (для ОСВ по субконто).',
    )
    opening_qty = fields.Float(string='Opening Qty', digits='Product Unit')
    turnover_qty_in = fields.Float(string='Qty In', digits='Product Unit')
    turnover_qty_out = fields.Float(string='Qty Out', digits='Product Unit')
    closing_qty = fields.Float(string='Closing Qty', digits='Product Unit')
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
