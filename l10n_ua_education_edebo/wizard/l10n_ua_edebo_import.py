"""Wizard for importing contingent lists from ЄДЕБО.

ЄДЕБО проводить обмін через XML формати, специфіковані МОН. Сам формат
закритий і регулярно змінюється — цей wizard надає базовий CSV-парсер
та точку розширення `_parse_custom()` для реальних форматів.
"""
import csv
import io
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


CSV_REQUIRED_COLS = {'last_name', 'first_name', 'birthdate', 'member_type'}


class L10nUaEdeboImport(models.TransientModel):
    _name = 'l10n_ua.edebo.import'
    _description = 'Імпорт з ЄДЕБО'

    file = fields.Binary(string='Файл', required=True)
    filename = fields.Char(string='Назва файлу')
    file_format = fields.Selection([
        ('csv', 'CSV (UTF-8)'),
        ('custom', 'Інший — обробити плагіном'),
    ], string='Формат', default='csv', required=True)
    encoding = fields.Char(string='Кодування', default='utf-8')
    academic_year_id = fields.Many2one(
        'l10n_ua.education.academic.year', string='Навчальний рік',
        required=True,
        default=lambda self: self.env['l10n_ua.education.academic.year'].search([
            ('is_active', '=', True),
            ('company_id', '=', self.env.company.id),
        ], limit=1))
    default_member_state = fields.Selection([
        ('applicant', 'Заявник'),
        ('enrolled', 'Зараховано'),
        ('studying', 'Навчається'),
    ], default='enrolled', required=True,
       help='У який стан створювати імпортованих записів')
    dry_run = fields.Boolean(
        string='Перевірочний прогін',
        default=True,
        help='Не записувати у базу — лише показати скільки записів буде створено / оновлено.')

    result_log = fields.Text(string='Результат', readonly=True)

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Завантажте файл.'))
        content = self.file.content.decode(self.encoding or 'utf-8', errors='replace')
        if self.file_format == 'csv':
            rows = self._parse_csv(content)
        else:
            rows = self._parse_custom(content)

        result = self._process_rows(rows, persist=not self.dry_run)
        if self.dry_run:
            self.result_log = (
                _('Перевірочний прогін (нічого не збережено):\n'
                  '  знайдено рядків: %(rows)s\n'
                  '  буде створено партнерів: %(p_new)s\n'
                  '  буде оновлено партнерів: %(p_upd)s\n'
                  '  буде створено учасників: %(m_new)s\n'
                  '  буде оновлено учасників: %(m_upd)s',
                  rows=result['rows'], p_new=result['p_new'],
                  p_upd=result['p_upd'], m_new=result['m_new'],
                  m_upd=result['m_upd']))
        else:
            self.result_log = (
                _('Імпорт виконано:\n'
                  '  створено партнерів: %(p_new)s\n'
                  '  оновлено партнерів: %(p_upd)s\n'
                  '  створено учасників: %(m_new)s\n'
                  '  оновлено учасників: %(m_upd)s',
                  p_new=result['p_new'], p_upd=result['p_upd'],
                  m_new=result['m_new'], m_upd=result['m_upd']))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _parse_csv(self, content):
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames or not CSV_REQUIRED_COLS.issubset(reader.fieldnames):
            raise UserError(_(
                'CSV повинен містити заголовки: %(req)s.\nОтримано: %(got)s.',
                req=', '.join(sorted(CSV_REQUIRED_COLS)),
                got=', '.join(reader.fieldnames or [])))
        out = []
        for row in reader:
            try:
                birthdate = datetime.strptime(row['birthdate'].strip(), '%Y-%m-%d').date()
            except (ValueError, KeyError):
                raise UserError(_('Некоректна дата народження у рядку: %s', row))
            full_name = f"{row['last_name'].strip()} {row['first_name'].strip()}"
            if row.get('middle_name'):
                full_name += f" {row['middle_name'].strip()}"
            out.append({
                'name': full_name,
                'birthdate': birthdate,
                'member_type': row['member_type'].strip(),
                'student_number': (row.get('student_number') or '').strip() or False,
                'rnokpp': (row.get('rnokpp') or '').strip() or False,
            })
        return out

    def _parse_custom(self, content):
        """Override in plugin modules to handle real ЄДЕБО XML formats."""
        raise UserError(_(
            'Формат «Інший» потребує плагіну. Установіть відповідний модуль '
            'для вашого формату ЄДЕБО (наприклад, l10n_ua_education_edebo_xml).'))

    def _process_rows(self, rows, persist=True):
        """Process parsed rows.

        Якщо persist=False — лише підраховує, що БУДЕ зроблено (dry-run),
        не пишучи у базу. Це дозволяє тестам не використовувати rollback,
        який заборонений всередині транзакції тесту.
        """
        Partner = self.env['res.partner']
        Member = self.env['l10n_ua.education.contingent.member']
        p_new = p_upd = m_new = m_upd = 0
        member_type_keys = {k for k, _ in Member._fields['member_type'].selection}

        for row in rows:
            mtype = row['member_type'] if row['member_type'] in member_type_keys else 'student'
            # Match partner by RNOKPP if provided, otherwise by name
            partner = False
            if row['rnokpp']:
                partner = Partner.search([('vat', '=', row['rnokpp'])], limit=1)
            if not partner:
                partner = Partner.search([
                    ('name', '=', row['name']),
                    ('is_company', '=', False),
                ], limit=1)
            if partner:
                p_upd += 1
            else:
                p_new += 1
                if persist:
                    partner = Partner.create({
                        'name': row['name'],
                        'is_company': False,
                        'vat': row['rnokpp'] or False,
                    })
                else:
                    partner = None  # marker for dry-run

            # Match member by student_number or (partner + year). In dry-run, if partner
            # is None we can't match — count as new.
            member = False
            if persist and partner:
                if row['student_number']:
                    member = Member.search([
                        ('student_number', '=', row['student_number']),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                if not member:
                    member = Member.search([
                        ('partner_id', '=', partner.id),
                        ('academic_year_id', '=', self.academic_year_id.id),
                    ], limit=1)
            if member:
                m_upd += 1
                member.write({
                    'state': self.default_member_state,
                    'student_number': row['student_number'] or member.student_number,
                })
            else:
                m_new += 1
                if persist and partner:
                    Member.create({
                        'partner_id': partner.id,
                        'member_type': mtype,
                        'academic_year_id': self.academic_year_id.id,
                        'student_number': row['student_number'] or False,
                        'state': self.default_member_state,
                    })

        return {
            'rows': len(rows), 'p_new': p_new, 'p_upd': p_upd,
            'm_new': m_new, 'm_upd': m_upd,
        }
