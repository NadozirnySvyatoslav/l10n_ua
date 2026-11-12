"""Експорт/імпорт плану в Excel у вигляді матриці «статті × періоди».

Аркуш «План»: колонки «Код статті», «Стаття», «Аналітика», далі по колонці на
кожен період плану (2026-01 / 2026-Q1 / 2026) і «Разом». Саме цей аркуш
читається при імпорті: стаття шукається за кодом (або назвою), аналітика —
за кодом (або назвою), порожня клітинка періоду пропускається.
Аркуш «Виконання» — план/факт/відхилення по рядках, лише для читання.
"""

import base64
import io

import xlsxwriter

from odoo import fields, models, _
from odoo.exceptions import UserError


# Перші три колонки читаються за позицією, тож заголовки можна перекладати.
FIXED_COLUMNS = 3


class L10nUaBudgetXlsxWizard(models.TransientModel):
    _name = 'l10n_ua.budget.xlsx.wizard'
    _description = 'Budget Excel Export/Import'

    plan_id = fields.Many2one('l10n_ua.budget.plan', string='Budget', required=True, ondelete='cascade')
    mode = fields.Selection([('export', 'Export'), ('import', 'Import')], required=True, default='export')
    file_data = fields.Binary(string='File')
    file_name = fields.Char(string='File Name')
    import_result = fields.Text(string='Result', readonly=True)

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Експорт
    # ------------------------------------------------------------------

    def _export_xlsx(self):
        plan = self.plan_id
        buckets = plan._get_buckets()
        labels = [plan._bucket_label(b[0]) for b in buckets]
        column_of = {b[0]: i for i, b in enumerate(buckets)}

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        bold = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})

        sheet = workbook.add_worksheet(_('Plan'))
        headers = [_('Item Code'), _('Item'), _('Analytic')] + labels + [_('Total')]
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)
        sheet.set_column(0, 0, 14)
        sheet.set_column(1, 1, 45)
        sheet.set_column(2, 2, 25)
        sheet.set_column(FIXED_COLUMNS, FIXED_COLUMNS + len(labels), 14)
        sheet.freeze_panes(1, FIXED_COLUMNS)

        rows = {}
        for line in plan.line_ids:
            key = (line.item_id, line.analytic_account_id)
            # None — періоду без рядка: клітинка лишається порожньою, і імпорт
            # не створить зайвих нульових рядків.
            rows.setdefault(key, [None] * len(buckets))
            col = column_of.get(line.date_from)
            if col is not None:
                rows[key][col] = (rows[key][col] or 0.0) + line.planned_amount
        ordered = sorted(rows.items(), key=lambda kv: (kv[0][0].sequence, kv[0][0].code or '',
                                                       kv[0][0].name, kv[0][1].name or ''))
        for row, ((item, analytic), amounts) in enumerate(ordered, start=1):
            sheet.write(row, 0, item.code or '')
            sheet.write(row, 1, item.name)
            sheet.write(row, 2, analytic.code or analytic.name or '')
            for col, amount in enumerate(amounts):
                if amount is not None:
                    sheet.write_number(row, FIXED_COLUMNS + col, amount, money)
            sheet.write_number(row, FIXED_COLUMNS + len(amounts),
                               sum(a for a in amounts if a is not None), money_bold)

        report = workbook.add_worksheet(_('Execution'))
        headers = [_('Item Code'), _('Item'), _('Analytic'), _('Period'), _('Planned'),
                   _('Actual'), _('Deviation'), _('Execution, %')]
        for col, header in enumerate(headers):
            report.write(0, col, header, bold)
        report.set_column(1, 1, 45)
        report.set_column(2, 3, 18)
        report.set_column(4, 7, 14)
        for row, line in enumerate(plan.line_ids, start=1):
            report.write(row, 0, line.item_id.code or '')
            report.write(row, 1, line.item_id.name)
            report.write(row, 2, line.analytic_account_id.display_name or '')
            report.write(row, 3, plan._bucket_label(line.date_from))
            report.write_number(row, 4, line.planned_amount, money)
            report.write_number(row, 5, line.actual_amount, money)
            report.write_number(row, 6, line.variance_amount, money)
            report.write_number(row, 7, line.execution_pct)
        workbook.close()
        return output.getvalue()

    def action_export(self):
        self.ensure_one()
        self.write({
            'file_data': base64.b64encode(self._export_xlsx()),
            'file_name': f'{self.plan_id.name}.xlsx'.replace('/', '-'),
        })
        return self._reopen()

    # ------------------------------------------------------------------
    # Імпорт
    # ------------------------------------------------------------------

    def _read_rows(self):
        try:
            import openpyxl
        except ImportError as exc:  # pragma: no cover - openpyxl входить у залежності Odoo
            raise UserError(_('The openpyxl Python library is required to import Excel files.')) from exc
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(base64.b64decode(self.file_data)),
                                              read_only=True, data_only=True)
        except Exception as exc:
            raise UserError(_('The file is not a valid Excel (.xlsx) workbook.')) from exc
        sheet = workbook.worksheets[0]
        return [list(row) for row in sheet.iter_rows(values_only=True)]

    def _find_item(self, code, name):
        Item = self.env['l10n_ua.budget.item']
        domain = [('budget_type', '=', self.plan_id.budget_type),
                  ('company_id', 'in', [False, self.plan_id.company_id.id])]
        if code:
            item = Item.search(domain + [('code', '=', code)], limit=1)
            if item:
                return item
        if name:
            return Item.search(domain + [('name', '=ilike', name)], limit=1)
        return Item

    def _find_analytic(self, value):
        Analytic = self.env['account.analytic.account']
        if not value:
            return Analytic
        domain = [('company_id', 'in', [False, self.plan_id.company_id.id])]
        return (Analytic.search(domain + [('code', '=', value)], limit=1)
                or Analytic.search(domain + [('name', '=ilike', value)], limit=1))

    def action_import(self):
        self.ensure_one()
        plan = self.plan_id
        if plan.state != 'draft':
            raise UserError(_('Only a draft budget can be imported into.'))
        if not self.file_data:
            raise UserError(_('Please choose a file to import.'))
        rows = self._read_rows()
        if not rows:
            raise UserError(_('The file is empty.'))

        buckets = {plan._bucket_label(b[0]): b for b in plan._get_buckets()}
        bucket_cols = {}
        for col, header in enumerate(rows[0]):
            if col < FIXED_COLUMNS or header is None:
                continue
            label = str(header).strip()
            if label in buckets:
                bucket_cols[col] = buckets[label]
        if not bucket_cols:
            raise UserError(_('No column header matches a period of the budget (expected e.g. %s).',
                              ', '.join(list(buckets)[:3])))

        existing = {(l.item_id.id, l.analytic_account_id.id, l.date_from): l for l in plan.line_ids}
        created = updated = 0
        errors = []
        create_vals = []
        for row_no, row in enumerate(rows[1:], start=2):
            code = str(row[0]).strip() if len(row) > 0 and row[0] is not None else ''
            name = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ''
            if not code and not name:
                continue
            item = self._find_item(code, name)
            if not item:
                errors.append(_('Row %(row)s: budget item "%(item)s" not found.', row=row_no, item=code or name))
                continue
            analytic_value = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ''
            analytic = self._find_analytic(analytic_value) if analytic_value else plan.analytic_account_id
            if analytic_value and not analytic:
                errors.append(_('Row %(row)s: analytic account "%(analytic)s" not found.',
                                row=row_no, analytic=analytic_value))
                continue
            for col, (date_from, date_to) in bucket_cols.items():
                value = row[col] if col < len(row) else None
                if value is None or value == '':
                    continue
                try:
                    amount = float(str(value).replace(' ', '').replace(',', '.')) \
                        if isinstance(value, str) else float(value)
                except ValueError:
                    errors.append(_('Row %(row)s: "%(value)s" is not a number.', row=row_no, value=value))
                    continue
                line = existing.get((item.id, analytic.id, date_from))
                if isinstance(line, dict):
                    # Той самий рядок двічі у файлі — береться останнє значення.
                    line['planned_amount'] = amount
                elif line:
                    if plan.currency_id.compare_amounts(line.planned_amount, amount):
                        line.planned_amount = amount
                        updated += 1
                else:
                    vals = {
                        'plan_id': plan.id,
                        'item_id': item.id,
                        'analytic_account_id': analytic.id,
                        'date_from': date_from,
                        'date_to': date_to,
                        'planned_amount': amount,
                    }
                    create_vals.append(vals)
                    existing[(item.id, analytic.id, date_from)] = vals
                    created += 1
        if errors:
            raise UserError('\n'.join(errors))
        self.env['l10n_ua.budget.line'].create(create_vals)
        self.import_result = _('Lines created: %(created)s, updated: %(updated)s.',
                               created=created, updated=updated)
        return self._reopen()
