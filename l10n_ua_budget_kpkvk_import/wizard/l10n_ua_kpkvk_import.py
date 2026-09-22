"""Wizard for bulk-loading КПКВК directory from CSV or DBF."""
import csv
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaKpkvkImport(models.TransientModel):
    _name = 'l10n_ua.kpkvk.import'
    _description = 'Імпорт довідника КПКВК'

    file = fields.Binary(string='Файл', required=True)
    filename = fields.Char(string='Назва файлу')
    file_format = fields.Selection([
        ('csv', 'CSV (UTF-8)'),
        ('dbf', 'DBF (Казначейство)'),
    ], string='Формат', default='csv', required=True)
    encoding = fields.Char(string='Кодування', default='utf-8')
    year = fields.Integer(
        string='Бюджетний рік', required=True,
        default=lambda self: fields.Date.today().year,
        help='Рік, у якому затверджені програми. Один КПКВК-код може існувати '
             'в різних роках з різними назвами.')
    overwrite = fields.Boolean(
        string='Перезаписати існуючі',
        help='Якщо запис з таким кодом+роком уже існує — оновити назву і поля.')
    result_log = fields.Text(readonly=True)

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Завантажте файл.'))
        raw = self.file.content
        if self.file_format == 'csv':
            rows = self._parse_csv(raw)
        else:
            rows = self._parse_dbf(raw)
        created, updated, skipped = self._upsert(rows)
        self.result_log = (
            _('Завантажено рядків: %(n)s\n'
              '  створено: %(c)s\n'
              '  оновлено: %(u)s\n'
              '  пропущено: %(s)s',
              n=len(rows), c=created, u=updated, s=skipped))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _parse_csv(self, raw):
        text = raw.decode(self.encoding or 'utf-8', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        required = {'code', 'name'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise UserError(_(
                'CSV повинен містити заголовки: %(req)s.\nОтримано: %(got)s.',
                req=', '.join(sorted(required)),
                got=', '.join(reader.fieldnames or [])))
        out = []
        for row in reader:
            code = (row.get('code') or '').strip()
            name = (row.get('name') or '').strip()
            if not code or not name:
                continue
            out.append({
                'code': code, 'name': name,
                'description': (row.get('description') or '').strip() or False,
            })
        return out

    def _parse_dbf(self, raw):
        """Use l10n_ua_budget_treasury_dbf reader if available.

        Field mapping (synonyms):
        * code: KOD, KOD_KPKVK, PROG_KOD
        * name: NAZVA, NAME, NAZWA, PROG_NAZ
        """
        try:
            from odoo.addons.l10n_ua_budget_treasury_dbf.models.dbf_reader \
                import read_dbf_records, DbfReadError
        except ImportError:
            raise UserError(_(
                'Для імпорту DBF потрібно встановити модуль '
                '`l10n_ua_budget_treasury_dbf`.'))
        try:
            records = list(read_dbf_records(raw, encoding=self.encoding or 'cp866'))
        except DbfReadError as e:
            raise UserError(_('Не вдалося прочитати DBF: %s', str(e)))

        code_synonyms = ('KOD', 'KOD_KPKVK', 'PROG_KOD', 'CODE')
        name_synonyms = ('NAZVA', 'NAME', 'NAZWA', 'PROG_NAZ', 'NAZW')
        out = []
        for row in records:
            code = None
            name = None
            for k in code_synonyms:
                if k in row and row[k]:
                    code = str(row[k]).strip()
                    break
            for k in name_synonyms:
                if k in row and row[k]:
                    name = str(row[k]).strip()
                    break
            if code and name:
                out.append({'code': code, 'name': name})
        return out

    def _upsert(self, rows):
        Kpkvk = self.env['l10n_ua.kpkvk']
        created = updated = skipped = 0
        for row in rows:
            existing = Kpkvk.search([
                ('code', '=', row['code']),
                ('year', '=', self.year),
            ], limit=1)
            if existing:
                if self.overwrite:
                    existing.write({
                        'name': row['name'],
                        'description': row.get('description') or existing.description,
                    })
                    updated += 1
                else:
                    skipped += 1
            else:
                vals = {
                    'code': row['code'],
                    'name': row['name'],
                    'year': self.year,
                }
                if row.get('description'):
                    vals['description'] = row['description']
                try:
                    Kpkvk.create(vals)
                    created += 1
                except Exception:
                    skipped += 1
        return created, updated, skipped
