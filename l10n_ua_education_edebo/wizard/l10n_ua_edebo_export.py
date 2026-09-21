"""Wizard for exporting contingent to ЄДЕБО-compatible CSV."""
import base64
import csv
import io

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class L10nUaEdeboExport(models.TransientModel):
    _name = 'l10n_ua.edebo.export'
    _description = 'Експорт у ЄДЕБО'

    academic_year_id = fields.Many2one(
        'l10n_ua.education.academic.year', string='Навчальний рік',
        required=True,
        default=lambda self: self.env['l10n_ua.education.academic.year'].search([
            ('is_active', '=', True),
            ('company_id', '=', self.env.company.id),
        ], limit=1))
    state_filter = fields.Selection([
        ('all', 'Усі стани'),
        ('active', 'Тільки активні (enrolled / studying)'),
        ('graduated', 'Тільки випущені'),
    ], string='Фільтр', default='active', required=True)
    file = fields.Binary(string='Файл експорту', readonly=True)
    filename = fields.Char(string='Назва файлу', readonly=True)

    def action_export(self):
        self.ensure_one()
        domain = [
            ('academic_year_id', '=', self.academic_year_id.id),
            ('company_id', '=', self.env.company.id),
        ]
        if self.state_filter == 'active':
            domain.append(('state', 'in', ('enrolled', 'studying')))
        elif self.state_filter == 'graduated':
            domain.append(('state', '=', 'graduated'))

        members = self.env['l10n_ua.education.contingent.member'].search(domain)
        if not members:
            raise UserError(_('Немає записів для експорту за обраним фільтром.'))

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            'student_number', 'last_name', 'first_name', 'middle_name',
            'birthdate', 'rnokpp', 'member_type', 'state',
            'group', 'date_enrolled',
        ])
        writer.writeheader()
        for m in members:
            full = (m.partner_id.name or '').strip()
            parts = full.split(' ', 2)
            last_name = parts[0] if parts else ''
            first_name = parts[1] if len(parts) > 1 else ''
            middle_name = parts[2] if len(parts) > 2 else ''
            writer.writerow({
                'student_number': m.student_number or '',
                'last_name': last_name,
                'first_name': first_name,
                'middle_name': middle_name,
                'birthdate': '',  # No birthdate field on member; pull from partner if needed
                'rnokpp': m.partner_id.vat or '',
                'member_type': m.member_type,
                'state': m.state,
                'group': m.group_id.name or '',
                'date_enrolled': str(m.date_enrolled) if m.date_enrolled else '',
            })

        content = buf.getvalue().encode('utf-8')
        self.write({
            'file': base64.b64encode(content).decode(),
            'filename': f"edebo_export_{self.academic_year_id.name.replace('/', '_')}.csv",
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
