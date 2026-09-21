import base64
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class L10nUaVatRegister(models.Model):
    _name = 'l10n_ua.vat.register'
    _description = 'VAT Register (Реєстр ПН)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc, register_type'

    name = fields.Char(
        string='Назва',
        compute='_compute_name',
        store=True,
    )
    register_type = fields.Selection(
        selection=[
            ('issued', 'Видані ПН'),
            ('received', 'Отримані ПН'),
        ],
        string='Тип реєстру',
        required=True,
        tracking=True,
    )
    period_id = fields.Many2one(
        'l10n_ua.tax.period',
        string='Податковий період',
        required=True,
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
            ('confirmed', 'Підтверджено'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )
    line_ids = fields.One2many(
        'l10n_ua.vat.register.line',
        'register_id',
        string='Рядки',
    )
    # Totals
    total_base = fields.Monetary(
        string='Загальний обсяг',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_vat = fields.Monetary(
        string='Загальний ПДВ',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    line_count = fields.Integer(
        string='Кількість записів',
        compute='_compute_totals',
        store=True,
    )

    @api.depends('register_type', 'period_id')
    def _compute_name(self):
        type_labels = {'issued': 'Видані ПН', 'received': 'Отримані ПН'}
        for rec in self:
            type_name = type_labels.get(rec.register_type, '')
            period_name = rec.period_id.name if rec.period_id else ''
            rec.name = f'Реєстр {type_name} — {period_name}'

    @api.depends('line_ids.base_amount', 'line_ids.vat_amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_base = sum(rec.line_ids.mapped('base_amount'))
            rec.total_vat = sum(rec.line_ids.mapped('vat_amount'))
            rec.line_count = len(rec.line_ids)

    def action_compute(self):
        """Auto-fill register lines from tax invoices in the period."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Розрахунок можливий тільки для чернеток.'))
            rec.line_ids.unlink()
            rec._generate_lines()

    def _generate_lines(self):
        """Search tax invoices for the period and create register lines."""
        self.ensure_one()
        period = self.period_id
        if not period:
            return

        invoices = self.env['l10n_ua.tax.invoice'].search([
            ('invoice_type', '=', self.register_type),
            ('date', '>=', period.date_start),
            ('date', '<=', period.date_end),
            ('company_id', '=', self.company_id.id),
            ('state', '!=', 'cancelled'),
        ], order='date, number')

        lines_vals = []
        for seq, inv in enumerate(invoices, 1):
            # Compute rate breakdown from invoice lines
            base_20 = vat_20 = base_14 = vat_14 = 0.0
            base_7 = vat_7 = base_0 = base_exempt = 0.0
            for line in inv.line_ids:
                if line.vat_rate == '20':
                    base_20 += line.base_amount
                    vat_20 += line.vat_amount
                elif line.vat_rate == '14':
                    base_14 += line.base_amount
                    vat_14 += line.vat_amount
                elif line.vat_rate == '7':
                    base_7 += line.base_amount
                    vat_7 += line.vat_amount
                elif line.vat_rate == '0':
                    base_0 += line.base_amount
                elif line.vat_rate == 'exempt':
                    base_exempt += line.base_amount

            lines_vals.append({
                'register_id': self.id,
                'sequence': seq,
                'date': inv.date,
                'doc_type': inv.doc_type,
                'tax_invoice_id': inv.id,
                'partner_id': inv.partner_id.id,
                'invoice_number': inv.number,
                'invoice_date': inv.date,
                'base_amount': inv.total_base,
                'vat_amount': inv.total_vat,
                'base_20': base_20,
                'vat_20': vat_20,
                'base_14': base_14,
                'vat_14': vat_14,
                'base_7': base_7,
                'vat_7': vat_7,
                'base_0': base_0,
                'base_exempt': base_exempt,
            })

        self.env['l10n_ua.vat.register.line'].create(lines_vals)

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Можна підтвердити тільки чернетки.'))
        self.write({'state': 'confirmed'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_export_xlsx(self):
        """Export VAT register to XLSX."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_('Бібліотека xlsxwriter не встановлена.'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_register_xlsx(workbook)
        workbook.close()
        output.seek(0)

        filename = f'Реєстр_ПН_{self.register_type}_{self.period_id.name}.xlsx'
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

    def _write_register_xlsx(self, workbook):
        """Write register data to XLSX workbook."""
        self.ensure_one()
        type_label = 'Видані' if self.register_type == 'issued' else 'Отримані'
        sheet = workbook.add_worksheet(f'Реєстр {type_label}')

        # Formats
        header_fmt = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'text_wrap': True, 'bg_color': '#D9E1F2',
        })
        cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        money_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter',
        })
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 12, 'align': 'center',
        })

        # Title
        sheet.merge_range('A1:L1', f'Реєстр {type_label} податкових накладних', title_fmt)
        sheet.merge_range('A2:L2', f'за {self.period_id.name}  {self.company_id.name}', title_fmt)

        # Headers (row 3)
        headers = [
            '№ з/п', 'Дата ПН', '№ ПН', 'Вид',
            'Контрагент', 'ІПН',
            'Обсяг 20%', 'ПДВ 20%',
            'Обсяг 14%', 'ПДВ 14%',
            'Обсяг 7%', 'ПДВ 7%',
        ]
        widths = [6, 12, 12, 6, 30, 14, 14, 14, 14, 14, 14, 14]
        for col, (h, w) in enumerate(zip(headers, widths)):
            sheet.set_column(col, col, w)
            sheet.write(3, col, h, header_fmt)

        # Data
        for row, line in enumerate(self.line_ids.sorted('sequence'), 4):
            doc_labels = {'pn': 'ПН', 'rk': 'РК', 'md': 'МД', 'bo': 'БО'}
            sheet.write(row, 0, line.sequence, cell_fmt)
            sheet.write(row, 1, str(line.date) if line.date else '', cell_fmt)
            sheet.write(row, 2, line.invoice_number or '', cell_fmt)
            sheet.write(row, 3, doc_labels.get(line.doc_type, ''), cell_fmt)
            sheet.write(row, 4, line.partner_id.name if line.partner_id else '', cell_fmt)
            sheet.write(row, 5, line.partner_ipn or '', cell_fmt)
            sheet.write(row, 6, line.base_20, money_fmt)
            sheet.write(row, 7, line.vat_20, money_fmt)
            sheet.write(row, 8, line.base_14, money_fmt)
            sheet.write(row, 9, line.vat_14, money_fmt)
            sheet.write(row, 10, line.base_7, money_fmt)
            sheet.write(row, 11, line.vat_7, money_fmt)

        # Totals
        total_row = len(self.line_ids) + 4
        total_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'num_format': '#,##0.00',
        })
        sheet.write(total_row, 0, '', total_fmt)
        sheet.merge_range(total_row, 1, total_row, 5, 'ВСЬОГО:', total_fmt)
        sheet.write(total_row, 6, sum(self.line_ids.mapped('base_20')), total_fmt)
        sheet.write(total_row, 7, sum(self.line_ids.mapped('vat_20')), total_fmt)
        sheet.write(total_row, 8, sum(self.line_ids.mapped('base_14')), total_fmt)
        sheet.write(total_row, 9, sum(self.line_ids.mapped('vat_14')), total_fmt)
        sheet.write(total_row, 10, sum(self.line_ids.mapped('base_7')), total_fmt)
        sheet.write(total_row, 11, sum(self.line_ids.mapped('vat_7')), total_fmt)


class L10nUaVatRegisterLine(models.Model):
    _name = 'l10n_ua.vat.register.line'
    _description = 'VAT Register Line'
    _order = 'sequence, date, id'

    register_id = fields.Many2one(
        'l10n_ua.vat.register',
        string='Реєстр',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(
        string='№ з/п',
        default=10,
    )
    date = fields.Date(
        string='Дата',
        required=True,
    )
    doc_type = fields.Selection(
        selection=[
            ('pn', 'ПН'),
            ('rk', 'РК'),
            ('md', 'МД'),
            ('bo', 'БО'),
        ],
        string='Вид',
        default='pn',
    )
    tax_invoice_id = fields.Many2one(
        'l10n_ua.tax.invoice',
        string='Податкова накладна',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Контрагент',
        required=True,
    )
    partner_ipn = fields.Char(
        related='partner_id.ipn',
        string='ІПН',
    )
    invoice_number = fields.Char(
        string='Номер ПН',
    )
    invoice_date = fields.Date(
        string='Дата ПН',
    )
    # Total
    base_amount = fields.Monetary(
        string='Обсяг постачання',
        currency_field='currency_id',
    )
    vat_amount = fields.Monetary(
        string='Сума ПДВ',
        currency_field='currency_id',
    )
    total_amount = fields.Monetary(
        string='Загальна сума',
        compute='_compute_total_amount',
        store=True,
        currency_field='currency_id',
    )
    # Rate breakdown
    base_20 = fields.Monetary(string='Обсяг 20%', currency_field='currency_id')
    vat_20 = fields.Monetary(string='ПДВ 20%', currency_field='currency_id')
    base_14 = fields.Monetary(string='Обсяг 14%', currency_field='currency_id')
    vat_14 = fields.Monetary(string='ПДВ 14%', currency_field='currency_id')
    base_7 = fields.Monetary(string='Обсяг 7%', currency_field='currency_id')
    vat_7 = fields.Monetary(string='ПДВ 7%', currency_field='currency_id')
    base_0 = fields.Monetary(string='Обсяг 0%', currency_field='currency_id')
    base_exempt = fields.Monetary(string='Звільнено', currency_field='currency_id')

    currency_id = fields.Many2one(
        'res.currency',
        related='register_id.currency_id',
    )

    @api.depends('base_amount', 'vat_amount')
    def _compute_total_amount(self):
        for line in self:
            line.total_amount = line.base_amount + line.vat_amount
