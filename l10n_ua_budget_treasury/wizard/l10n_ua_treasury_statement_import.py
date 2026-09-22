"""Skeleton wizard for ДКСУ statement imports.

Реальні формати виписок ДКСУ варіюються (DBF, текстові колонкові формати,
іноді XML). Цей wizard забезпечує базову інфраструктуру:

* приймає файл і журнал-призначення,
* створює `account.bank.statement` із відповідними рядками,
* має точку розширення `_parse_lines(content)` для підключення конкретного парсера.

Поточна реалізація підтримує простий CSV з колонками:
    date,description,partner_name,amount,reference

Для реальних форматів — переозначити `_parse_lines` у дочірньому модулі
(наприклад, `l10n_ua_budget_treasury_dbf` для UTF8 DBF-форматів).
"""
import csv
import io
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaTreasuryStatementImport(models.TransientModel):
    _name = 'l10n_ua.treasury.statement.import'
    _description = 'Імпорт виписки ДКСУ'

    journal_id = fields.Many2one(
        'account.journal', string='Журнал', required=True,
        domain="[('ua_is_treasury', '=', True)]",
        help='Казначейський журнал, до якого прив\'язується виписка')
    file = fields.Binary(string='Файл виписки', required=True)
    filename = fields.Char(string='Назва файлу')
    file_format = fields.Selection([
        ('csv', 'CSV (UTF-8)'),
        ('custom', 'Інший — обробити плагіном'),
    ], string='Формат файлу', default='csv', required=True)
    encoding = fields.Char(string='Кодування', default='utf-8')

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Завантажте файл виписки.'))

        content = self.file.content.decode(self.encoding or 'utf-8', errors='replace')

        if self.file_format == 'csv':
            parsed_lines = self._parse_csv(content)
        else:
            parsed_lines = self._parse_custom(content)

        if not parsed_lines:
            raise UserError(_('У файлі не знайдено рядків для імпорту.'))

        statement = self._create_statement(parsed_lines)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'view_mode': 'form',
            'res_id': statement.id,
        }

    def _parse_csv(self, content):
        """Parse the default CSV format.

        Expected columns (header row required): date, description, partner_name,
        amount, reference. Date in YYYY-MM-DD, amount signed (positive = credit
        on the account, i.e. money in).
        """
        reader = csv.DictReader(io.StringIO(content))
        required = {'date', 'description', 'amount'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise UserError(_(
                'CSV повинен містити заголовки: %(req)s. Отримано: %(got)s.',
                req=', '.join(sorted(required)),
                got=', '.join(reader.fieldnames or [])))
        out = []
        for row in reader:
            try:
                date = datetime.strptime(row['date'].strip(), '%Y-%m-%d').date()
                amount = float(row['amount'].replace(',', '.').strip())
            except (ValueError, KeyError) as e:
                raise UserError(_('Помилка парсингу рядка %(row)s: %(err)s',
                                   row=row, err=str(e)))
            out.append({
                'date': date,
                'payment_ref': (row.get('description') or '').strip() or _('Виписка ДКСУ'),
                'amount': amount,
                'partner_name': (row.get('partner_name') or '').strip(),
                'ref': (row.get('reference') or '').strip(),
            })
        return out

    def _parse_custom(self, content):
        """Override in plugin modules for proprietary ДКСУ formats."""
        raise UserError(_(
            'Формат «Інший» потребує плагіну. Установіть відповідний модуль '
            '(наприклад, l10n_ua_budget_treasury_dbf) або імпортуйте через CSV.'))

    def _create_statement(self, parsed_lines):
        """Create an account.bank.statement with the parsed lines."""
        Statement = self.env['account.bank.statement']
        if not parsed_lines:
            raise UserError(_('Немає рядків для створення виписки.'))

        dates = sorted({l['date'] for l in parsed_lines})
        statement_vals = {
            'name': _('Виписка ДКСУ %(date_from)s - %(date_to)s',
                       date_from=dates[0], date_to=dates[-1]),
            'date': dates[-1],
            'line_ids': [
                (0, 0, {
                    'journal_id': self.journal_id.id,
                    'date': line['date'],
                    'payment_ref': line['payment_ref'],
                    'amount': line['amount'],
                    'ref': line.get('ref') or False,
                    'partner_name': line.get('partner_name') or False,
                }) for line in parsed_lines
            ],
        }
        return Statement.create(statement_vals)
