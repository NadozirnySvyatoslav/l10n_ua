import base64

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .dbf import build_dbf

# Структура файлу «Дані щодо співробітників» iFOBS.eSalary (для відкриття карток),
# windows-1251. Порядок і типи полів — за офіційним «Опис форматів iFOBS.eSalary».
# Каталог-залежні поля (коди областей НБУ, транслітерація LATFIO, структурована
# адреса) необов'язкові — лишаються порожніми; повну адресу вміщує ADRESS.
IFOBS_EMP_FIELDS = [
    ('BRANCHPART', 'N', 10, 0), ('FIO', 'C', 120, 0), ('SEX', 'C', 1, 0),
    ('LATFIO', 'C', 26, 0), ('BIRTHDAY', 'D', 8, 0), ('RESIDENT', 'N', 1, 0),
    ('PASSPSER', 'C', 20, 0), ('PASNOM', 'C', 20, 0), ('PASDAT', 'D', 8, 0),
    ('PASPLACE', 'C', 120, 0), ('INN', 'C', 10, 0), ('COUNTRY', 'N', 3, 0),
    ('ZIP', 'C', 6, 0), ('OBL', 'N', 2, 0), ('RN', 'C', 40, 0),
    ('TNP', 'C', 4, 0), ('NP', 'C', 36, 0), ('STREET', 'C', 40, 0),
    ('BUILDING', 'C', 10, 0), ('FLAT', 'C', 10, 0), ('PHONE', 'C', 20, 0),
    ('MOBPHONE', 'C', 20, 0), ('JOBPHONE', 'C', 20, 0), ('CCOUNTRY', 'N', 3, 0),
    ('CZIP', 'C', 6, 0), ('COBL', 'N', 2, 0), ('CRN', 'C', 40, 0),
    ('CTNP', 'C', 4, 0), ('CNP', 'C', 36, 0), ('CSTREET', 'C', 40, 0),
    ('CBUILDING', 'C', 10, 0), ('CFLAT', 'C', 10, 0), ('ADRESS', 'C', 254, 0),
    ('CADRESS', 'C', 254, 0), ('TABNOM', 'C', 15, 0), ('JOB', 'C', 40, 0),
]


class HrIfobsEmployeeExport(models.TransientModel):
    """Експорт даних працівників для відкриття карток у iFOBS (#195).

    Формує DBF «Дані щодо співробітників» (windows-1251) для завантаження в
    зарплатний проєкт iFOBS (Укргазбанк та інші iFOBS-банки).
    """
    _name = 'hr.ifobs.employee.export'
    _description = 'iFOBS Employee Data Export'

    employee_ids = fields.Many2many(
        'hr.employee', string='Employees', required=True,
        default=lambda self: self.env.context.get('active_ids', []))
    file_data = fields.Binary(string='File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)
    state = fields.Selection(
        [('choose', 'Choose'), ('done', 'Done')], default='choose')

    @staticmethod
    def _sex_code(employee):
        val = (getattr(employee, 'sex', False) or '').lower()
        if val in ('male', 'm', 'ч', 'чоловіча'):
            return 'M'
        if val in ('female', 'f', 'ж', 'жіноча'):
            return 'Ж'
        return ''

    def _employee_row(self, emp):
        phone_mob = emp.mobile_phone or getattr(emp, 'private_phone', '') or ''
        return {
            'BRANCHPART': 0,
            'FIO': emp.name or '',
            'SEX': self._sex_code(emp),
            'BIRTHDAY': emp.birthday or '',
            'RESIDENT': 1,
            'PASSPSER': getattr(emp, 'passport_series', '') or '',
            'PASNOM': getattr(emp, 'passport_id', '') or '',
            'PASDAT': getattr(emp, 'passport_issued_date', '') or '',
            'PASPLACE': getattr(emp, 'passport_issued_by', '') or '',
            'INN': emp.rnokpp or '',
            'COUNTRY': 804 if (emp.country_id and emp.country_id.code == 'UA') else 0,
            'ZIP': getattr(emp, 'registration_zip', '') or '',
            'PHONE': getattr(emp, 'private_phone', '') or '',
            'MOBPHONE': phone_mob,
            'JOBPHONE': emp.work_phone or '',
            # Structured address columns above stay empty, so ADRESS must carry
            # the whole thing — index, region, city and street included.
            'ADRESS': emp._get_ua_registration_address_display(),
            'TABNOM': '',
            'JOB': emp.job_id.name if emp.job_id else '',
        }

    def action_generate(self):
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_('Оберіть працівників.'))
        problems = []
        for emp in self.employee_ids:
            missing = []
            if not emp.rnokpp:
                missing.append('РНОКПП')
            if not getattr(emp, 'passport_id', False):
                missing.append('номер паспорта')
            if not getattr(emp, 'passport_issued_date', False):
                missing.append('дата видачі паспорта')
            if not (emp.work_phone or emp.mobile_phone
                    or getattr(emp, 'private_phone', False)):
                missing.append('телефон')
            if missing:
                problems.append('%s: %s' % (emp.name, ', '.join(missing)))
        if problems:
            raise UserError(_(
                'Бракує обов\'язкових даних для iFOBS:\n- %s'
            ) % '\n- '.join(problems))

        rows = [self._employee_row(emp) for emp in self.employee_ids]
        content = build_dbf(IFOBS_EMP_FIELDS, rows)
        self.file_data = base64.b64encode(content).decode()
        self.file_name = 'ifobs_employees.dbf'
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
