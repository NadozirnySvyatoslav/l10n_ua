import base64
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

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
    # Row 1.2 — operations taxed at 7%
    line_1_2_base = fields.Monetary(
        string='р.1.2 Обсяг 7%',
        currency_field='currency_id',
        help='Операції на митній території, що оподатковуються за ставкою 7%',
    )
    line_1_2_vat = fields.Monetary(
        string='р.1.2 ПДВ 7%',
        currency_field='currency_id',
    )
    # Row 1.3 — operations taxed at 14%
    line_1_3_base = fields.Monetary(
        string='р.1.3 Обсяг 14%',
        currency_field='currency_id',
        help='Операції на митній території, що оподатковуються за ставкою 14%',
    )
    line_1_3_vat = fields.Monetary(
        string='р.1.3 ПДВ 14%',
        currency_field='currency_id',
    )
    # Row 2.1 — export operations at 0%
    line_2_base = fields.Monetary(
        string='р.2.1 Експорт 0%',
        currency_field='currency_id',
        help='Операції з вивезення товарів за межі митної території (0%)',
    )
    # Row 2.2 — export operations exempt from VAT
    line_2_2_base = fields.Monetary(
        string='р.2.2 Експорт, звільнений',
        currency_field='currency_id',
        help='Операції з вивезення товарів, звільнені від оподаткування',
    )
    # Row 3 — other operations at 0%
    line_3_base = fields.Monetary(
        string='р.3 Інші 0%',
        currency_field='currency_id',
        help='Інші операції, що оподатковуються за нульовою ставкою',
    )
    # Row 5 — not object of taxation, supplies outside Ukraine, exempt
    line_5_base = fields.Monetary(
        string='р.5 Не об\'єкт / за межами / звільнені',
        currency_field='currency_id',
        help='Операції, що не є об\'єктом оподаткування, послуги з місцем постачання '
             'за межами України та операції, звільнені від оподаткування',
    )
    # Row 5.1 — of row 5: exempt operations
    line_5_1_base = fields.Monetary(
        string='р.5.1 У т.ч. звільнені',
        currency_field='currency_id',
        help='З рядка 5 — операції, звільнені від оподаткування',
    )
    # Row 7.1 — adjustments of supplies and liabilities (issued adjustment calculations)
    line_7_1_base = fields.Monetary(
        string='р.7.1 Коригування обсягів',
        currency_field='currency_id',
        help='Коригування обсягів постачання за розрахунками коригування (+/-)',
    )
    line_7_1_vat = fields.Monetary(
        string='р.7.1 Коригування ПЗ',
        currency_field='currency_id',
        help='Коригування податкових зобов\'язань за розрахунками коригування (+/-)',
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
    # Row 10.2 — domestic purchases at 7%
    line_10_2_base = fields.Monetary(
        string='р.10.2 Придбання 7%',
        currency_field='currency_id',
    )
    line_10_2_vat = fields.Monetary(
        string='р.10.2 ПК 7%',
        currency_field='currency_id',
    )
    # Row 10.3 — domestic purchases at 14%
    line_10_3_base = fields.Monetary(
        string='р.10.3 Придбання 14%',
        currency_field='currency_id',
    )
    line_10_3_vat = fields.Monetary(
        string='р.10.3 ПК 14%',
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
    # Row 11.2 — import purchases at 7%
    line_11_2_base = fields.Monetary(
        string='р.11.2 Імпорт 7%',
        currency_field='currency_id',
    )
    line_11_2_vat = fields.Monetary(
        string='р.11.2 ПК імпорт 7%',
        currency_field='currency_id',
    )
    # Row 11.3 — import purchases at 14%
    line_11_3_base = fields.Monetary(
        string='р.11.3 Імпорт 14%',
        currency_field='currency_id',
    )
    line_11_3_vat = fields.Monetary(
        string='р.11.3 ПК імпорт 14%',
        currency_field='currency_id',
    )
    # Row 10.4 — domestic purchases at 0% / without VAT (base only)
    line_10_4_base = fields.Monetary(
        string='р.10.4 Придбання 0% / без ПДВ',
        currency_field='currency_id',
    )
    # Row 11.4 — imported goods without VAT (base only)
    line_11_4_base = fields.Monetary(
        string='р.11.4 Імпорт без ПДВ',
        currency_field='currency_id',
    )
    # Row 14 — correction of tax credit (adjustment calculations)
    line_14_vat = fields.Monetary(
        string='р.14 Коригування ПК',
        currency_field='currency_id',
        help='Коригування податкового кредиту',
    )
    # Row 15 — correction under 192.1.1 without registered adjustment (decreases credit)
    line_15_vat = fields.Monetary(
        string='р.15 Коригування ПК (п.п. 192.1.1)',
        currency_field='currency_id',
        help='Повернення товару/послуги або передоплати за відсутності зареєстрованого '
             'розрахунку коригування; зменшує податковий кредит',
    )
    # Row 16.1 — negative value carried from row 21 of the previous period
    line_16_1_vat = fields.Monetary(
        string='р.16.1 Від\'ємне значення попереднього періоду',
        currency_field='currency_id',
        help='Значення рядка 21 декларації за попередній звітний період',
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
    # Section III — Розрахунки за звітний період
    # Rows 18 - 21
    # =====================================================

    # Row 18 — VAT payable (liabilities > credit)
    line_18_vat = fields.Monetary(
        string='р.18 ПДВ до сплати',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Позитивне значення різниці (р.9 - р.17) — до сплати в бюджет',
    )
    # Row 19 — negative value (credit > liabilities)
    line_19_vat = fields.Monetary(
        string='р.19 Від\'ємне значення',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Від\'ємне значення різниці (р.17 - р.9). Без бюджетного відшкодування '
             'й погашення боргу воно повністю переходить у рядок 21',
    )
    # Сума за п. 200-1.3 ПКУ (Σнакл у СЕА ПДВ) — службове поле рядка 19.1
    vat_limit_amount = fields.Monetary(
        string='Сума за п. 200-1.3 (Σнакл)',
        currency_field='currency_id',
        help='Сума, на яку платник має право зареєструвати ПН/РК в ЄРПН, на дату подання '
             '(кабінет → Дані СЕА ПДВ). Від\'ємне значення понад неї йде в рядок 19.1, '
             'решта — у рядок 20. При розрахунку береться з останнього розрахунку '
             'реєстраційного ліміту, якщо не вказана.',
    )
    # Row 19.1 — excess of the negative value over the limit (to the next period)
    line_19_1_vat = fields.Monetary(
        string='р.19.1 Перевищення над Σнакл',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    # Row 20 — negative value within the limit; 20.3 — its remainder after 20.1/20.2
    line_20_vat = fields.Monetary(
        string='р.20 У межах Σнакл',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    line_20_3_vat = fields.Monetary(
        string='р.20.3 Залишок (р.20 − 20.1 − 20.2)',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    d2_line_ids = fields.One2many(
        'l10n_ua.vat.declaration.d2.line',
        'declaration_id',
        string='Д2: розшифровка від\'ємного значення',
        copy=False,
    )
    # Row 21 — negative value carried to the tax credit of the next period
    line_21_vat = fields.Monetary(
        string='р.21 До ПК наступного періоду',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
        help='Від\'ємне значення, що зараховується до податкового кредиту наступного '
             'періоду (переноситься до рядка 16.1)',
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
        string='Від\'ємне значення',
        related='line_19_vat',
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
        'line_1_1_vat', 'line_1_2_vat', 'line_1_3_vat', 'line_7_1_vat',
        'line_10_1_vat', 'line_10_2_vat', 'line_10_3_vat',
        'line_11_1_vat', 'line_11_2_vat', 'line_11_3_vat',
        'line_14_vat', 'line_15_vat', 'line_16_1_vat', 'vat_limit_amount',
    )
    def _compute_totals(self):
        for rec in self:
            # Section I — total liabilities (row 9)
            rec.line_9_vat = (
                rec.line_1_1_vat + rec.line_1_2_vat + rec.line_1_3_vat + rec.line_7_1_vat
            )
            # Section II — total credit (row 17 = 10.1..10.3 + 11.1..11.3 + 14 - 15 + 16)
            rec.line_17_vat = (
                rec.line_10_1_vat + rec.line_10_2_vat + rec.line_10_3_vat
                + rec.line_11_1_vat + rec.line_11_2_vat + rec.line_11_3_vat
                + rec.line_14_vat - rec.line_15_vat + rec.line_16_1_vat
            )
            # Section III — result
            diff = rec.line_9_vat - rec.line_17_vat
            rec.line_18_vat = max(diff, 0.0)
            rec.line_19_vat = max(-diff, 0.0)
            # 19.1 — перевищення над Σнакл, 20 — у межах. Без погашення боргу (20.1)
            # і відшкодування (20.2): 20.3 = 20, а 21 = 19.1 + 20.3 = 19.
            limit = max(rec.vat_limit_amount or 0.0, 0.0)
            rec.line_19_1_vat = float_round(max(rec.line_19_vat - limit, 0.0),
                                            precision_digits=0)
            rec.line_20_vat = rec.line_19_vat - rec.line_19_1_vat
            rec.line_20_3_vat = rec.line_20_vat
            rec.line_21_vat = rec.line_19_1_vat + rec.line_20_3_vat

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
        """Заповнити рядки з реєстрів виданих і отриманих ПН/РК за період.

        Рядки декларації — у цілих гривнях (тип DGdecimal0 у XSD J0200126), тож
        кожен рядок округлюємо, а підсумки 9/17/18/19/21 рахуються вже з округлених.
        ПН — рядки 1.x / 10.x / 11.x, РК — коригування 7.1 (видані) і 14 (отримані).
        """
        self.ensure_one()
        issued = self.register_issued_id.line_ids
        received = self.register_received_id.line_ids

        def total(lines, field):
            return float_round(sum(lines.mapped(field)), precision_digits=0)

        issued_pn = issued.filtered(lambda l: l.doc_type != 'rk')
        issued_rk = issued.filtered(lambda l: l.doc_type == 'rk')
        received_pn = received.filtered(lambda l: l.doc_type != 'rk')
        received_rk = received.filtered(lambda l: l.doc_type == 'rk')
        imported = received_pn.filtered(lambda l: l.tax_invoice_id.is_import)
        domestic = received_pn - imported

        self.write({
            'line_1_1_base': total(issued_pn, 'base_20'),
            'line_1_1_vat': total(issued_pn, 'vat_20'),
            'line_1_2_base': total(issued_pn, 'base_7'),
            'line_1_2_vat': total(issued_pn, 'vat_7'),
            'line_1_3_base': total(issued_pn, 'base_14'),
            'line_1_3_vat': total(issued_pn, 'vat_14'),
            'line_2_base': total(issued_pn, 'base_0'),
            'line_5_base': total(issued_pn, 'base_exempt'),
            'line_5_1_base': total(issued_pn, 'base_exempt'),
            'line_7_1_base': total(issued_rk, 'base_amount'),
            'line_7_1_vat': total(issued_rk, 'vat_amount'),
            'line_10_1_base': total(domestic, 'base_20'),
            'line_10_1_vat': total(domestic, 'vat_20'),
            'line_10_2_base': total(domestic, 'base_7'),
            'line_10_2_vat': total(domestic, 'vat_7'),
            'line_10_3_base': total(domestic, 'base_14'),
            'line_10_3_vat': total(domestic, 'vat_14'),
            'line_11_1_base': total(imported, 'base_20'),
            'line_11_1_vat': total(imported, 'vat_20'),
            'line_11_2_base': total(imported, 'base_7'),
            'line_11_2_vat': total(imported, 'vat_7'),
            'line_11_3_base': total(imported, 'base_14'),
            'line_11_3_vat': total(imported, 'vat_14'),
            'line_14_vat': total(received_rk, 'vat_amount'),
            'line_16_1_vat': self._previous_negative_value(),
        })
        if not self.vat_limit_amount:
            limit = self.env['l10n_ua.vat.erpn.limit'].search([
                ('company_id', '=', self.company_id.id),
                ('date', '<=', fields.Date.context_today(self)),
            ], order='date desc', limit=1)
            if limit:
                self.vat_limit_amount = float_round(limit.limit_amount, precision_digits=0)
        self._fill_d2_lines()

    def _previous_negative_value(self):
        """Рядок 21 декларації за попередній звітний період (→ рядок 16.1)."""
        previous = self._previous_declaration()
        return previous.line_21_vat if previous else 0.0

    def _previous_declaration(self):
        self.ensure_one()
        start = self.period_id.date_start
        if not start:
            return self.browse()
        return self.search([
            ('company_id', '=', self.company_id.id),
            ('period_id.date_end', '<', start),
            ('state', 'in', ('calculated', 'submitted', 'accepted')),
            ('id', '!=', self.id),
        ]).sorted(lambda d: d.period_id.date_end)[-1:]

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
            'datas': base64.b64encode(output.read()),
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
            ('1.1', 'Операції на митній території за основною ставкою', self.line_1_1_base, self.line_1_1_vat),
            ('1.2', 'Операції на митній території за ставкою 7%', self.line_1_2_base, self.line_1_2_vat),
            ('1.3', 'Операції на митній території за ставкою 14%', self.line_1_3_base, self.line_1_3_vat),
            ('2.1', 'Вивезення товарів за нульовою ставкою', self.line_2_base, None),
            ('2.2', 'Вивезення товарів, звільнене від оподаткування', self.line_2_2_base, None),
            ('3', 'Інші операції за нульовою ставкою', self.line_3_base, None),
            ('5', 'Не є об\'єктом / за межами України / звільнені', self.line_5_base, None),
            ('5.1', 'у т.ч. звільнені від оподаткування', self.line_5_1_base, None),
            ('7.1', 'Коригування обсягів постачання та податкових зобов\'язань', self.line_7_1_base, self.line_7_1_vat),
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
            ('10.1', 'Придбання на митній території з основною ставкою', self.line_10_1_base, self.line_10_1_vat),
            ('10.2', 'Придбання на митній території зі ставкою 7%', self.line_10_2_base, self.line_10_2_vat),
            ('10.3', 'Придбання на митній території зі ставкою 14%', self.line_10_3_base, self.line_10_3_vat),
            ('10.4', 'Придбання з нульовою ставкою та/або без ПДВ', self.line_10_4_base, None),
            ('11.1', 'Ввезені товари з основною ставкою', self.line_11_1_base, self.line_11_1_vat),
            ('11.2', 'Ввезені товари зі ставкою 7%', self.line_11_2_base, self.line_11_2_vat),
            ('11.3', 'Ввезені товари зі ставкою 14%', self.line_11_3_base, self.line_11_3_vat),
            ('11.4', 'Ввезені товари без ПДВ', self.line_11_4_base, None),
            ('14', 'Коригування податкового кредиту', None, self.line_14_vat),
            ('15', 'Коригування ПК за п.п. 192.1.1 (-)', None, self.line_15_vat),
            ('16.1', 'Від\'ємне значення попереднього періоду (р.21)', None, self.line_16_1_vat),
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

        sheet.write(row, 0, '19', total_fmt)
        sheet.write(row, 1, 'Від\'ємне значення (р.17 - р.9)', total_fmt)
        sheet.write(row, 2, '', total_fmt)
        sheet.write(row, 3, self.line_19_vat, total_fmt)
        row += 1

        sheet.write(row, 0, '21', cell_fmt)
        sheet.write(row, 1, 'Зараховується до ПК наступного періоду', cell_fmt)
        sheet.write(row, 2, '', money_fmt)
        sheet.write(row, 3, self.line_21_vat, money_fmt)
