import base64
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

AGING_BUCKETS = [
    ('current', 'Поточна', 0),
    ('1_7', '1-7 дн.', 7),
    ('8_14', '8-14 дн.', 14),
    ('15_30', '15-30 дн.', 30),
    ('31_60', '31-60 дн.', 60),
    ('61_90', '61-90 дн.', 90),
    ('over_90', '>90 дн.', None),
]

REPORT_TYPE_LABELS = {
    'receivable': 'ДЕБІТОРСЬКУ',
    'payable': 'КРЕДИТОРСЬКУ',
    'both': 'ДЕБІТОРСЬКУ ТА КРЕДИТОРСЬКУ',
}


class L10nUaAgingReport(models.Model):
    _name = 'l10n_ua.aging.report'
    _description = 'AR/AP Aging Report (Звіт про заборгованість)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Назва',
        compute='_compute_name',
        store=True,
    )
    date = fields.Date(
        string='Дата звіту',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    report_type = fields.Selection(
        selection=[
            ('receivable', 'Дебіторська заборгованість'),
            ('payable', 'Кредиторська заборгованість'),
            ('both', 'Обидва типи'),
        ],
        string='Тип звіту',
        required=True,
        default='receivable',
        tracking=True,
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
    state = fields.Selection(
        selection=[
            ('draft', 'Чернетка'),
            ('calculated', 'Розраховано'),
            ('confirmed', 'Підтверджено'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )
    line_ids = fields.One2many(
        'l10n_ua.aging.report.line',
        'report_id',
        string='Рядки',
    )

    # Totals
    total_amount = fields.Monetary(
        string='Усього',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_current = fields.Monetary(
        string='Поточна',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_1_7 = fields.Monetary(
        string='1-7 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_8_14 = fields.Monetary(
        string='8-14 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_15_30 = fields.Monetary(
        string='15-30 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_31_60 = fields.Monetary(
        string='31-60 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_61_90 = fields.Monetary(
        string='61-90 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_over_90 = fields.Monetary(
        string='>90 дн.',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    partner_count = fields.Integer(
        string='Контрагентів',
        compute='_compute_totals',
        store=True,
    )

    @api.depends('report_type', 'date')
    def _compute_name(self):
        type_labels = {
            'receivable': 'Дебіторська заборгованість',
            'payable': 'Кредиторська заборгованість',
            'both': 'Заборгованість (ДЗ/КЗ)',
        }
        for rec in self:
            label = type_labels.get(rec.report_type, '')
            if rec.date:
                rec.name = f'{label} на {rec.date}'
            else:
                rec.name = label or _('Новий звіт')

    @api.depends(
        'line_ids.total_amount', 'line_ids.amount_current',
        'line_ids.amount_1_7', 'line_ids.amount_8_14',
        'line_ids.amount_15_30', 'line_ids.amount_31_60',
        'line_ids.amount_61_90', 'line_ids.amount_over_90',
    )
    def _compute_totals(self):
        for rec in self:
            lines = rec.line_ids
            rec.total_amount = sum(lines.mapped('total_amount'))
            rec.total_current = sum(lines.mapped('amount_current'))
            rec.total_1_7 = sum(lines.mapped('amount_1_7'))
            rec.total_8_14 = sum(lines.mapped('amount_8_14'))
            rec.total_15_30 = sum(lines.mapped('amount_15_30'))
            rec.total_31_60 = sum(lines.mapped('amount_31_60'))
            rec.total_61_90 = sum(lines.mapped('amount_61_90'))
            rec.total_over_90 = sum(lines.mapped('amount_over_90'))
            rec.partner_count = len(lines)

    # =====================================================
    # Actions
    # =====================================================

    def action_compute(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(_('Неможливо перерахувати підтверджений звіт.'))
            rec._compute_aging_data()
        self.write({'state': 'calculated'})

    def action_confirm(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Підтвердити можна тільки розрахований звіт.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        for rec in self:
            if rec.state == 'confirmed':
                pass  # allow reset
        self.write({'state': 'draft'})

    def _compute_aging_data(self):
        """Calculate aging data from account.move.line grouped by partner."""
        self.ensure_one()
        self.line_ids.unlink()

        account_types = self._get_account_types()
        if not account_types:
            return

        report_date = self.date or fields.Date.context_today(self)

        # Raw SQL for performance — group residual amounts by partner + aging bucket
        self.env.cr.execute("""
            SELECT
                aml.partner_id,
                aa.account_type,
                COALESCE(aml.date_maturity, aml.date) AS due_date,
                aml.amount_residual
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE am.state = 'posted'
              AND aml.amount_residual != 0
              AND aml.partner_id IS NOT NULL
              AND aml.company_id = %s
              AND aa.account_type IN %s
        """, (self.company_id.id, tuple(account_types)))

        # Aggregate by (partner_id, account_type)
        data = {}  # key: (partner_id, account_type) -> bucket amounts
        for row in self.env.cr.fetchall():
            partner_id, acc_type, due_date, residual = row
            key = (partner_id, acc_type)
            if key not in data:
                data[key] = {
                    'current': 0.0, '1_7': 0.0, '8_14': 0.0,
                    '15_30': 0.0, '31_60': 0.0, '61_90': 0.0,
                    'over_90': 0.0, 'count': 0,
                }
            days_overdue = (report_date - due_date).days
            bucket = self._get_bucket(days_overdue)
            # For receivable: positive residual = money owed TO us
            # For payable: negative residual = money WE owe
            amount = abs(residual)
            data[key][bucket] += amount
            data[key]['count'] += 1

        # Create report lines
        line_vals = []
        for (partner_id, acc_type), buckets in data.items():
            total = sum(v for k, v in buckets.items() if k != 'count')
            if total < 0.01:
                continue
            line_vals.append({
                'report_id': self.id,
                'partner_id': partner_id,
                'account_type': 'receivable' if acc_type == 'asset_receivable' else 'payable',
                'total_amount': total,
                'amount_current': buckets['current'],
                'amount_1_7': buckets['1_7'],
                'amount_8_14': buckets['8_14'],
                'amount_15_30': buckets['15_30'],
                'amount_31_60': buckets['31_60'],
                'amount_61_90': buckets['61_90'],
                'amount_over_90': buckets['over_90'],
                'move_line_count': buckets['count'],
            })

        # Sort by total descending
        line_vals.sort(key=lambda x: x['total_amount'], reverse=True)
        Line = self.env['l10n_ua.aging.report.line']
        for vals in line_vals:
            Line.create(vals)

    def _get_account_types(self):
        if self.report_type == 'receivable':
            return ['asset_receivable']
        elif self.report_type == 'payable':
            return ['liability_payable']
        else:
            return ['asset_receivable', 'liability_payable']

    @staticmethod
    def _get_bucket(days_overdue):
        if days_overdue <= 0:
            return 'current'
        elif days_overdue <= 7:
            return '1_7'
        elif days_overdue <= 14:
            return '8_14'
        elif days_overdue <= 30:
            return '15_30'
        elif days_overdue <= 60:
            return '31_60'
        elif days_overdue <= 90:
            return '61_90'
        else:
            return 'over_90'

    # =====================================================
    # XLSX Export
    # =====================================================

    def action_export_xlsx(self):
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_('Бібліотека xlsxwriter не встановлена.'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_aging_xlsx(workbook)
        workbook.close()
        output.seek(0)

        type_suffix = {
            'receivable': 'ДЗ',
            'payable': 'КЗ',
            'both': 'ДЗ_КЗ',
        }.get(self.report_type, '')
        filename = f'Заборгованість_{type_suffix}_{self.date}.xlsx'

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _write_aging_xlsx(self, workbook):
        self.ensure_one()
        sheet = workbook.add_worksheet('Заборгованість')

        # Formats
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center',
        })
        subtitle_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center',
        })
        header_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'text_wrap': True,
            'align': 'center', 'valign': 'vcenter',
            'bg_color': '#4472C4', 'font_color': 'white',
        })
        cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        money_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter',
        })
        warn_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter',
            'bg_color': '#FFF2CC',
        })
        danger_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter',
            'bg_color': '#FCE4D6', 'font_color': '#C00000',
        })
        total_fmt = workbook.add_format({
            'bold': True, 'border': 2, 'valign': 'vcenter',
        })
        total_money_fmt = workbook.add_format({
            'bold': True, 'border': 2, 'num_format': '#,##0.00',
            'valign': 'vcenter',
        })
        type_fmt = workbook.add_format({
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })

        # Column widths
        sheet.set_column(0, 0, 40)  # Partner
        sheet.set_column(1, 1, 10)  # Type
        sheet.set_column(2, 2, 16)  # Total
        sheet.set_column(3, 9, 14)  # Buckets

        # Title
        type_label = REPORT_TYPE_LABELS.get(self.report_type, '')
        row = 0
        sheet.merge_range(row, 0, row, 9,
                          f'ЗВІТ ПРО {type_label} ЗАБОРГОВАНІСТЬ', title_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 9,
                          f'станом на {self.date.strftime("%d.%m.%Y")}    '
                          f'{self.company_id.name}', subtitle_fmt)
        row += 2

        # Headers
        headers = [
            'Контрагент', 'Тип', 'Усього', 'Поточна',
            '1-7 дн.', '8-14 дн.', '15-30 дн.', '31-60 дн.',
            '61-90 дн.', '>90 дн.',
        ]
        for col, h in enumerate(headers):
            sheet.write(row, col, h, header_fmt)
        row += 1

        # Data rows
        type_labels = {'receivable': 'ДЗ', 'payable': 'КЗ'}
        for line in self.line_ids.sorted(lambda l: l.total_amount, reverse=True):
            sheet.write(row, 0, line.partner_id.name or '', cell_fmt)
            sheet.write(row, 1, type_labels.get(line.account_type, ''), type_fmt)
            sheet.write(row, 2, line.total_amount, money_fmt)
            sheet.write(row, 3, line.amount_current, money_fmt)
            sheet.write(row, 4, line.amount_1_7, money_fmt)
            sheet.write(row, 5, line.amount_8_14, money_fmt)
            sheet.write(row, 6, line.amount_15_30, money_fmt)
            sheet.write(row, 7, line.amount_31_60, warn_fmt if line.amount_31_60 else money_fmt)
            sheet.write(row, 8, line.amount_61_90, danger_fmt if line.amount_61_90 else money_fmt)
            sheet.write(row, 9, line.amount_over_90, danger_fmt if line.amount_over_90 else money_fmt)
            row += 1

        # Totals
        sheet.write(row, 0, 'РАЗОМ', total_fmt)
        sheet.write(row, 1, '', total_fmt)
        sheet.write(row, 2, self.total_amount, total_money_fmt)
        sheet.write(row, 3, self.total_current, total_money_fmt)
        sheet.write(row, 4, self.total_1_7, total_money_fmt)
        sheet.write(row, 5, self.total_8_14, total_money_fmt)
        sheet.write(row, 6, self.total_15_30, total_money_fmt)
        sheet.write(row, 7, self.total_31_60, total_money_fmt)
        sheet.write(row, 8, self.total_61_90, total_money_fmt)
        sheet.write(row, 9, self.total_over_90, total_money_fmt)


class L10nUaAgingReportLine(models.Model):
    _name = 'l10n_ua.aging.report.line'
    _description = 'Aging Report Line'
    _order = 'total_amount desc'

    report_id = fields.Many2one(
        'l10n_ua.aging.report',
        string='Звіт',
        required=True,
        ondelete='cascade',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Контрагент',
        required=True,
    )
    account_type = fields.Selection(
        selection=[
            ('receivable', 'Дебіторська'),
            ('payable', 'Кредиторська'),
        ],
        string='Тип',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='report_id.currency_id',
    )
    total_amount = fields.Monetary(
        string='Усього',
        currency_field='currency_id',
    )
    amount_current = fields.Monetary(
        string='Поточна',
        currency_field='currency_id',
    )
    amount_1_7 = fields.Monetary(
        string='1-7 дн.',
        currency_field='currency_id',
    )
    amount_8_14 = fields.Monetary(
        string='8-14 дн.',
        currency_field='currency_id',
    )
    amount_15_30 = fields.Monetary(
        string='15-30 дн.',
        currency_field='currency_id',
    )
    amount_31_60 = fields.Monetary(
        string='31-60 дн.',
        currency_field='currency_id',
    )
    amount_61_90 = fields.Monetary(
        string='61-90 дн.',
        currency_field='currency_id',
    )
    amount_over_90 = fields.Monetary(
        string='>90 дн.',
        currency_field='currency_id',
    )
    move_line_count = fields.Integer(
        string='Кількість проводок',
    )

    def action_view_move_lines(self):
        """Drill-down: open source journal items for this partner."""
        self.ensure_one()
        report = self.report_id
        acc_type = 'asset_receivable' if self.account_type == 'receivable' else 'liability_payable'
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('account_id.account_type', '=', acc_type),
            ('parent_state', '=', 'posted'),
            ('amount_residual', '!=', 0),
            ('company_id', '=', report.company_id.id),
        ]
        return {
            'name': f'{self.partner_id.name} — {self.get_type_label()}',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def get_type_label(self):
        return 'ДЗ' if self.account_type == 'receivable' else 'КЗ'
