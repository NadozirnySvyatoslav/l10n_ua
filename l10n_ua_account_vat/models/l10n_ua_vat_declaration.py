import base64
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class L10nUaVatDeclaration(models.Model):
    _name = 'l10n_ua.vat.declaration'
    _description = 'VAT Declaration (Декларація з ПДВ)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id desc'

    name = fields.Char(
        string='Назва',
        compute='_compute_name',
        store=True,
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
            ('calculated', 'Розраховано'),
            ('submitted', 'Подано'),
            ('accepted', 'Прийнято'),
        ],
        string='Стан',
        default='draft',
        tracking=True,
    )
    # Links to registers
    register_issued_id = fields.Many2one(
        'l10n_ua.vat.register',
        string='Реєстр виданих ПН',
        compute='_compute_registers',
    )
    register_received_id = fields.Many2one(
        'l10n_ua.vat.register',
        string='Реєстр отриманих ПН',
        compute='_compute_registers',
    )

    # =====================================================
    # Section I — Податкові зобов'язання (Tax Liabilities)
    # Rows 1.1 - 9
    # =====================================================

    # Row 1.1 — operations taxed at 20%
    line_1_1_base = fields.Monetary(
        string='р.1.1 Обсяг 20%',
        currency_field='currency_id',
        help='Операції на митній території, що оподатковуються за ставкою 20%',
    )
    line_1_1_vat = fields.Monetary(
        string='р.1.1 ПДВ 20%',
        currency_field='currency_id',
    )
    # Row 1.2 — operations taxed at 14%
    line_1_2_base = fields.Monetary(
        string='р.1.2 Обсяг 14%',
        currency_field='currency_id',
        help='Операції на митній території, що оподатковуються за ставкою 14%',
    )
    line_1_2_vat = fields.Monetary(
        string='р.1.2 ПДВ 14%',
        currency_field='currency_id',
    )
    # Row 1.3 — operations taxed at 7%
    line_1_3_base = fields.Monetary(
        string='р.1.3 Обсяг 7%',
        currency_field='currency_id',
        help='Операції на митній території, що оподатковуються за ставкою 7%',
    )
    line_1_3_vat = fields.Monetary(
        string='р.1.3 ПДВ 7%',
        currency_field='currency_id',
    )
    # Row 2 — export operations at 0%
    line_2_base = fields.Monetary(
        string='р.2 Експорт 0%',
        currency_field='currency_id',
        help='Операції з вивезення товарів за межі митної території (0%)',
    )
    # Row 3 — other operations at 0%
    line_3_base = fields.Monetary(
        string='р.3 Інші 0%',
        currency_field='currency_id',
        help='Інші операції, що оподатковуються за нульовою ставкою',
    )
    # Row 4 — import operations (base only, VAT paid at customs)
    line_4_base = fields.Monetary(
        string='р.4 Імпорт',
        currency_field='currency_id',
        help='Операції з імпорту товарів (ПДВ сплачено на митниці)',
    )
    # Row 5 — exempt operations
    line_5_base = fields.Monetary(
        string='р.5 Звільнені',
        currency_field='currency_id',
        help='Операції, звільнені від оподаткування',
    )
    # Row 6 — operations not subject to VAT / not object of taxation
    line_6_base = fields.Monetary(
        string='р.6 Не є об\'єктом',
        currency_field='currency_id',
        help='Обсяг операцій, що не є об\'єктом оподаткування',
    )
    # Row 9 — total tax liabilities (computed)
    line_9_vat = fields.Monetary(
        string='р.9 Усього зобов\'язання',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Усього податкових зобов\'язань',
    )

    # =====================================================
    # Section II — Податковий кредит (Tax Credit)
    # Rows 10.1 - 17
    # =====================================================

    # Row 10.1 — domestic purchases at 20%
    line_10_1_base = fields.Monetary(
        string='р.10.1 Придбання 20%',
        currency_field='currency_id',
        help='Придбання на митній території за ставкою 20%',
    )
    line_10_1_vat = fields.Monetary(
        string='р.10.1 ПК 20%',
        currency_field='currency_id',
    )
    # Row 10.2 — domestic purchases at 14%
    line_10_2_base = fields.Monetary(
        string='р.10.2 Придбання 14%',
        currency_field='currency_id',
    )
    line_10_2_vat = fields.Monetary(
        string='р.10.2 ПК 14%',
        currency_field='currency_id',
    )
    # Row 10.3 — domestic purchases at 7%
    line_10_3_base = fields.Monetary(
        string='р.10.3 Придбання 7%',
        currency_field='currency_id',
    )
    line_10_3_vat = fields.Monetary(
        string='р.10.3 ПК 7%',
        currency_field='currency_id',
    )
    # Row 11.1 — import purchases at 20%
    line_11_1_base = fields.Monetary(
        string='р.11.1 Імпорт 20%',
        currency_field='currency_id',
    )
    line_11_1_vat = fields.Monetary(
        string='р.11.1 ПК імпорт 20%',
        currency_field='currency_id',
    )
    # Row 11.2 — import purchases at 14%
    line_11_2_base = fields.Monetary(
        string='р.11.2 Імпорт 14%',
        currency_field='currency_id',
    )
    line_11_2_vat = fields.Monetary(
        string='р.11.2 ПК імпорт 14%',
        currency_field='currency_id',
    )
    # Row 11.3 — import purchases at 7%
    line_11_3_base = fields.Monetary(
        string='р.11.3 Імпорт 7%',
        currency_field='currency_id',
    )
    line_11_3_vat = fields.Monetary(
        string='р.11.3 ПК імпорт 7%',
        currency_field='currency_id',
    )
    # Row 14 — correction of tax credit (adjustment calculations)
    line_14_vat = fields.Monetary(
        string='р.14 Коригування ПК',
        currency_field='currency_id',
        help='Коригування податкового кредиту',
    )
    # Row 17 — total tax credit (computed)
    line_17_vat = fields.Monetary(
        string='р.17 Усього кредит',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Усього податкового кредиту',
    )

    # =====================================================
    # Section III — Розрахунок (Result)
    # Rows 18 - 20
    # =====================================================

    # Row 18 — VAT payable (liabilities > credit)
    line_18_vat = fields.Monetary(
        string='р.18 ПДВ до сплати',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Позитивне значення різниці (р.9 - р.17) — до сплати в бюджет',
    )
    # Row 20 — VAT refundable (credit > liabilities)
    line_20_vat = fields.Monetary(
        string='р.20 ПДВ до відшкодування',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Від\'ємне значення різниці (р.17 - р.9) — бюджетне відшкодування',
    )
    # Row 20.2 — carry forward to next period
    line_20_2_vat = fields.Monetary(
        string='р.20.2 Зараховується до ПК наступного періоду',
        currency_field='currency_id',
        help='Сума, що зараховується до складу ПК наступного звітного періоду',
    )

    # =====================================================
    # Backwards-compatible aliases
    # =====================================================
    total_liabilities = fields.Monetary(
        string='Зобов\'язання',
        related='line_9_vat',
    )
    total_credit = fields.Monetary(
        string='Кредит',
        related='line_17_vat',
    )
    vat_payable = fields.Monetary(
        string='ПДВ до сплати',
        related='line_18_vat',
    )
    vat_refundable = fields.Monetary(
        string='ПДВ до відшкодування',
        related='line_20_vat',
    )

    @api.depends('period_id')
    def _compute_name(self):
        for rec in self:
            period_name = rec.period_id.name if rec.period_id else ''
            rec.name = f'Декларація з ПДВ — {period_name}'

    def _compute_registers(self):
        Register = self.env['l10n_ua.vat.register']
        for rec in self:
            rec.register_issued_id = Register.search([
                ('period_id', '=', rec.period_id.id),
                ('register_type', '=', 'issued'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)
            rec.register_received_id = Register.search([
                ('period_id', '=', rec.period_id.id),
                ('register_type', '=', 'received'),
                ('company_id', '=', rec.company_id.id),
            ], limit=1)

    @api.depends(
        'line_1_1_vat', 'line_1_2_vat', 'line_1_3_vat',
        'line_10_1_vat', 'line_10_2_vat', 'line_10_3_vat',
        'line_11_1_vat', 'line_11_2_vat', 'line_11_3_vat',
        'line_14_vat',
    )
    def _compute_totals(self):
        for rec in self:
            # Section I — total liabilities (row 9)
            rec.line_9_vat = (
                rec.line_1_1_vat + rec.line_1_2_vat + rec.line_1_3_vat
            )
            # Section II — total credit (row 17)
            rec.line_17_vat = (
                rec.line_10_1_vat + rec.line_10_2_vat + rec.line_10_3_vat
                + rec.line_11_1_vat + rec.line_11_2_vat + rec.line_11_3_vat
                + rec.line_14_vat
            )
            # Section III — result
            diff = rec.line_9_vat - rec.line_17_vat
            if diff > 0:
                rec.line_18_vat = diff
                rec.line_20_vat = 0.0
            else:
                rec.line_18_vat = 0.0
                rec.line_20_vat = abs(diff)

    # =====================================================
    # Actions
    # =====================================================

    def action_calculate(self):
        """Calculate declaration from VAT registers for the period."""
        for rec in self:
            if rec.state not in ('draft', 'calculated'):
                raise UserError(_('Розрахунок можливий тільки для чернеток.'))
            rec._calculate_from_registers()
        self.write({'state': 'calculated'})

    def _calculate_from_registers(self):
        """Fill declaration lines from issued and received registers."""
        self.ensure_one()
        Register = self.env['l10n_ua.vat.register']

        # Find issued register (tax liabilities)
        issued = Register.search([
            ('period_id', '=', self.period_id.id),
            ('register_type', '=', 'issued'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        # Find received register (tax credit)
        received = Register.search([
            ('period_id', '=', self.period_id.id),
            ('register_type', '=', 'received'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        vals = {}

        # Section I — from issued register
        if issued:
            lines = issued.line_ids
            vals.update({
                'line_1_1_base': sum(lines.mapped('base_20')),
                'line_1_1_vat': sum(lines.mapped('vat_20')),
                'line_1_2_base': sum(lines.mapped('base_14')),
                'line_1_2_vat': sum(lines.mapped('vat_14')),
                'line_1_3_base': sum(lines.mapped('base_7')),
                'line_1_3_vat': sum(lines.mapped('vat_7')),
                'line_2_base': sum(lines.mapped('base_0')),
                'line_5_base': sum(lines.mapped('base_exempt')),
            })
        else:
            vals.update({
                'line_1_1_base': 0, 'line_1_1_vat': 0,
                'line_1_2_base': 0, 'line_1_2_vat': 0,
                'line_1_3_base': 0, 'line_1_3_vat': 0,
                'line_2_base': 0, 'line_5_base': 0,
            })

        # Section II — from received register
        if received:
            lines = received.line_ids
            # Split domestic vs import
            domestic = lines.filtered(lambda l: not l.tax_invoice_id.is_import if l.tax_invoice_id else True)
            imported = lines.filtered(lambda l: l.tax_invoice_id.is_import if l.tax_invoice_id else False)

            vals.update({
                'line_10_1_base': sum(domestic.mapped('base_20')),
                'line_10_1_vat': sum(domestic.mapped('vat_20')),
                'line_10_2_base': sum(domestic.mapped('base_14')),
                'line_10_2_vat': sum(domestic.mapped('vat_14')),
                'line_10_3_base': sum(domestic.mapped('base_7')),
                'line_10_3_vat': sum(domestic.mapped('vat_7')),
                'line_11_1_base': sum(imported.mapped('base_20')),
                'line_11_1_vat': sum(imported.mapped('vat_20')),
                'line_11_2_base': sum(imported.mapped('base_14')),
                'line_11_2_vat': sum(imported.mapped('vat_14')),
                'line_11_3_base': sum(imported.mapped('base_7')),
                'line_11_3_vat': sum(imported.mapped('vat_7')),
            })
        else:
            vals.update({
                'line_10_1_base': 0, 'line_10_1_vat': 0,
                'line_10_2_base': 0, 'line_10_2_vat': 0,
                'line_10_3_base': 0, 'line_10_3_vat': 0,
                'line_11_1_base': 0, 'line_11_1_vat': 0,
                'line_11_2_base': 0, 'line_11_2_vat': 0,
                'line_11_3_base': 0, 'line_11_3_vat': 0,
            })

        self.write(vals)

    def action_submit(self):
        for rec in self:
            if rec.state != 'calculated':
                raise UserError(_('Подати можна тільки розраховану декларацію.'))
        self.write({'state': 'submitted'})

    def action_accept(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Прийняти можна тільки подану декларацію.'))
        self.write({'state': 'accepted'})

    def action_draft(self):
        for rec in self:
            if rec.state == 'accepted':
                raise UserError(_('Неможливо повернути прийняту декларацію в чернетку.'))
        self.write({'state': 'draft'})

    def action_view_vat_account_balance(self):
        """Open journal items filtered by VAT account (6411) for this period."""
        self.ensure_one()
        # Find account 6411 (VAT settlements)
        account = self.env['account.account'].search([
            ('code', '=like', '6411%'),
            ('company_ids', 'in', self.company_id.id),
        ], limit=1)
        if not account:
            raise UserError(_('Рахунок 6411 не знайдено в плані рахунків.'))

        domain = [('account_id', '=', account.id)]
        if self.period_id:
            if self.period_id.date_start:
                domain.append(('date', '>=', self.period_id.date_start))
            if self.period_id.date_end:
                domain.append(('date', '<=', self.period_id.date_end))

        return {
            'name': _('Рахунок 6411 — %s') % self.period_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'search_default_group_by_account': 1},
        }

    def action_create_vat_payment(self):
        """Open payment form pre-filled with VAT payable amount."""
        self.ensure_one()
        if self.line_18_vat <= 0:
            raise UserError(_('Немає суми ПДВ до сплати.'))

        return {
            'name': _('Сплата ПДВ'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_payment_type': 'outbound',
                'default_amount': self.line_18_vat,
                'default_ref': _('ПДВ за %s') % self.period_id.name,
            },
        }

    def action_export_xlsx(self):
        """Export VAT declaration to XLSX."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_('Бібліотека xlsxwriter не встановлена.'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_declaration_xlsx(workbook)
        workbook.close()
        output.seek(0)

        filename = f'Декларація_ПДВ_{self.period_id.name}.xlsx'
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

    def _write_declaration_xlsx(self, workbook):
        """Write declaration data to XLSX workbook."""
        self.ensure_one()
        sheet = workbook.add_worksheet('Декларація')

        # Formats
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center',
        })
        section_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'bg_color': '#D9E1F2',
            'border': 1,
        })
        header_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'text_wrap': True,
            'align': 'center', 'valign': 'vcenter', 'bg_color': '#E2EFDA',
        })
        cell_fmt = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        money_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'valign': 'vcenter',
        })
        total_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'num_format': '#,##0.00',
            'bg_color': '#FCE4D6',
        })

        sheet.set_column(0, 0, 8)   # Row number
        sheet.set_column(1, 1, 50)   # Description
        sheet.set_column(2, 2, 18)   # Base
        sheet.set_column(3, 3, 18)   # VAT

        # Title
        sheet.merge_range('A1:D1', 'ПОДАТКОВА ДЕКЛАРАЦІЯ З ПОДАТКУ НА ДОДАНУ ВАРТІСТЬ', title_fmt)
        sheet.merge_range('A2:D2', f'за {self.period_id.name}   {self.company_id.name}', title_fmt)

        # Headers
        row = 3
        sheet.write(row, 0, 'Рядок', header_fmt)
        sheet.write(row, 1, 'Показники', header_fmt)
        sheet.write(row, 2, 'Обсяги постачання (без ПДВ)', header_fmt)
        sheet.write(row, 3, 'Сума ПДВ', header_fmt)

        row = 4
        # Section I
        sheet.merge_range(row, 0, row, 3, 'Розділ I. Податкові зобов\'язання', section_fmt)
        row += 1

        decl_rows = [
            ('1.1', 'Операції на митній території за ставкою 20%', self.line_1_1_base, self.line_1_1_vat),
            ('1.2', 'Операції на митній території за ставкою 14%', self.line_1_2_base, self.line_1_2_vat),
            ('1.3', 'Операції на митній території за ставкою 7%', self.line_1_3_base, self.line_1_3_vat),
            ('2', 'Операції з вивезення товарів (експорт) 0%', self.line_2_base, None),
            ('3', 'Інші операції за нульовою ставкою', self.line_3_base, None),
            ('4', 'Операції з імпорту товарів', self.line_4_base, None),
            ('5', 'Операції, звільнені від оподаткування', self.line_5_base, None),
            ('6', 'Операції, що не є об\'єктом оподаткування', self.line_6_base, None),
        ]

        for rnum, desc, base, vat in decl_rows:
            sheet.write(row, 0, rnum, cell_fmt)
            sheet.write(row, 1, desc, cell_fmt)
            sheet.write(row, 2, base or 0, money_fmt)
            sheet.write(row, 3, vat or 0, money_fmt)
            row += 1

        # Row 9 total
        sheet.write(row, 0, '9', total_fmt)
        sheet.write(row, 1, 'УСЬОГО податкових зобов\'язань', total_fmt)
        sheet.write(row, 2, '', total_fmt)
        sheet.write(row, 3, self.line_9_vat, total_fmt)
        row += 1

        # Section II
        sheet.merge_range(row, 0, row, 3, 'Розділ II. Податковий кредит', section_fmt)
        row += 1

        credit_rows = [
            ('10.1', 'Придбання на митній території за ставкою 20%', self.line_10_1_base, self.line_10_1_vat),
            ('10.2', 'Придбання на митній території за ставкою 14%', self.line_10_2_base, self.line_10_2_vat),
            ('10.3', 'Придбання на митній території за ставкою 7%', self.line_10_3_base, self.line_10_3_vat),
            ('11.1', 'Імпорт товарів за ставкою 20%', self.line_11_1_base, self.line_11_1_vat),
            ('11.2', 'Імпорт товарів за ставкою 14%', self.line_11_2_base, self.line_11_2_vat),
            ('11.3', 'Імпорт товарів за ставкою 7%', self.line_11_3_base, self.line_11_3_vat),
            ('14', 'Коригування податкового кредиту', None, self.line_14_vat),
        ]

        for rnum, desc, base, vat in credit_rows:
            sheet.write(row, 0, rnum, cell_fmt)
            sheet.write(row, 1, desc, cell_fmt)
            sheet.write(row, 2, base or 0, money_fmt)
            sheet.write(row, 3, vat or 0, money_fmt)
            row += 1

        # Row 17 total
        sheet.write(row, 0, '17', total_fmt)
        sheet.write(row, 1, 'УСЬОГО податкового кредиту', total_fmt)
        sheet.write(row, 2, '', total_fmt)
        sheet.write(row, 3, self.line_17_vat, total_fmt)
        row += 1

        # Section III
        sheet.merge_range(row, 0, row, 3, 'Розділ III. Розрахунок суми податку', section_fmt)
        row += 1

        sheet.write(row, 0, '18', total_fmt)
        sheet.write(row, 1, 'Позитивне значення (р.9 - р.17) — до сплати', total_fmt)
        sheet.write(row, 2, '', total_fmt)
        sheet.write(row, 3, self.line_18_vat, total_fmt)
        row += 1

        sheet.write(row, 0, '20', total_fmt)
        sheet.write(row, 1, 'Від\'ємне значення (р.17 - р.9) — до відшкодування', total_fmt)
        sheet.write(row, 2, '', total_fmt)
        sheet.write(row, 3, self.line_20_vat, total_fmt)
        row += 1

        sheet.write(row, 0, '20.2', cell_fmt)
        sheet.write(row, 1, 'Зараховується до ПК наступного періоду', cell_fmt)
        sheet.write(row, 2, '', money_fmt)
        sheet.write(row, 3, self.line_20_2_vat, money_fmt)
