from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


PERSONAL_FIELDS = [
    # Standard Odoo personal data
    'name', 'gender', 'birthday', 'place_of_birth', 'country_of_birth',
    'marital', 'private_phone', 'private_email', 'private_street',
    'private_street2', 'private_city', 'private_zip', 'private_state_id',
    'private_country_id',
    # Ukrainian-specific personal data from l10n_ua_hr_base
    'rnokpp', 'document_type', 'passport_series', 'passport_number',
    'passport_issued_by', 'passport_issued_date', 'passport_record_number',
    'registration_address', 'registration_region_id', 'registration_city',
    'registration_zip', 'actual_address', 'actual_same_as_registration',
    'education_level_id', 'diploma_series', 'diploma_number', 'diploma_date',
    'military_status', 'military_category', 'military_rank_id',
    'military_specialty', 'military_fitness', 'military_document_number',
    'military_tcc_id', 'military_reservation', 'military_reservation_until',
    'military_reservplus_id',
    'disability_group', 'disability_reason', 'disability_document',
    'disability_date_from', 'disability_date_to',
    'chornobyl_category', 'veteran_status', 'spouse_rnokpp',
]


class HrEmployeeTransferWizard(models.TransientModel):
    _name = 'hr.employee.transfer.wizard'
    _description = 'Переведення співробітника в іншу компанію (КЗпП ст. 36 п. 5)'

    source_employee_id = fields.Many2one(
        'hr.employee', string='Співробітник (source)', required=True, readonly=True,
    )
    source_company_id = fields.Many2one(
        'res.company', string='Компанія (source)', required=True, readonly=True,
    )
    target_company_id = fields.Many2one(
        'res.company', string='Цільова компанія', required=True,
        domain="[('id', '!=', source_company_id)]",
    )

    dismissal_date = fields.Date(
        string='Дата звільнення', required=True, default=fields.Date.context_today,
    )
    dismissal_reason = fields.Text(
        string='Підстава звільнення', required=True,
        default='п. 5 ст. 36 КЗпП України — переведення на інше підприємство (за згодою працівника)',
    )
    hire_date = fields.Date(
        string='Дата прийняття',
        compute='_compute_hire_date', store=True, readonly=False,
    )

    new_department_id = fields.Many2one(
        'hr.department', string='Підрозділ (target)',
        domain="[('company_id', '=', target_company_id)]",
    )
    new_job_id = fields.Many2one(
        'hr.job', string='Посада (target)',
        domain="[('company_id', '=', target_company_id)]",
    )

    copy_bank_accounts = fields.Boolean(string='Копіювати банківські рахунки', default=True)
    copy_documents = fields.Boolean(string='Копіювати особові документи', default=True)
    copy_family_data = fields.Boolean(string='Копіювати сімейні дані (діти, подружжя)', default=True)

    vacation_transfer_mode = fields.Selection(
        [
            ('reset', 'Залишок згоряє (закон 2022)'),
            ('transfer', 'Перенести (за згодою сторін)'),
        ],
        string='Залишок відпустки', required=True, default='reset',
        help='Зміни в КЗпП 2022 року: накопичений залишок при переведенні згоряє. '
             'За згодою сторін може переноситися — оберіть "Перенести".',
    )

    @api.depends('dismissal_date')
    def _compute_hire_date(self):
        for wiz in self:
            wiz.hire_date = (wiz.dismissal_date + timedelta(days=1)) if wiz.dismissal_date else False

    @api.constrains('target_company_id', 'source_company_id')
    def _check_different_company(self):
        for wiz in self:
            if wiz.target_company_id == wiz.source_company_id:
                raise UserError(_('Цільова компанія має відрізнятися від поточної.'))

    @api.constrains('hire_date', 'dismissal_date')
    def _check_dates(self):
        for wiz in self:
            if wiz.hire_date and wiz.dismissal_date and wiz.hire_date < wiz.dismissal_date:
                raise UserError(_('Дата прийняття не може бути раніше за дату звільнення.'))

    def _prepare_new_employee_vals(self):
        self.ensure_one()
        source = self.source_employee_id
        vals = {
            'company_id': self.target_company_id.id,
            'department_id': self.new_department_id.id or False,
            'job_id': self.new_job_id.id or False,
            'previous_employee_id': source.id,
        }
        for fname in PERSONAL_FIELDS:
            if fname not in source._fields:
                continue
            value = source[fname]
            if hasattr(value, 'id'):
                vals[fname] = value.id if value else False
            else:
                vals[fname] = value
        if not self.copy_documents:
            for fname in ('passport_series', 'passport_number', 'passport_issued_by',
                          'passport_issued_date', 'passport_record_number',
                          'diploma_series', 'diploma_number', 'diploma_date',
                          'education_level_id'):
                vals.pop(fname, None)
        if not self.copy_family_data:
            vals.pop('spouse_rnokpp', None)
            vals.pop('marital', None)
        return vals

    def _copy_children(self, new_employee):
        if not self.copy_family_data:
            return
        Child = self.env['hr.employee.child']
        for child in self.source_employee_id.children_ids:
            copy_vals = child.copy_data()[0]
            copy_vals['employee_id'] = new_employee.id
            Child.sudo().create(copy_vals)

    def _copy_bank_accounts(self, new_employee):
        if not self.copy_bank_accounts or not self.source_employee_id.work_contact_id:
            return
        source_partner = self.source_employee_id.work_contact_id
        target_partner = new_employee.work_contact_id
        if not target_partner:
            return
        for bank in source_partner.bank_ids:
            copy_vals = bank.copy_data()[0]
            copy_vals['partner_id'] = target_partner.id
            copy_vals['company_id'] = self.target_company_id.id
            self.env['res.partner.bank'].sudo().create(copy_vals)

    def _create_dismissal_order(self):
        return self.env['hr.order'].with_company(self.source_company_id).sudo().create({
            'order_type': 'dismissal',
            'subject': 'Про припинення трудового договору (переведенням)',
            'employee_id': self.source_employee_id.id,
            'department_id': self.source_employee_id.department_id.id,
            'job_id': self.source_employee_id.job_id.id,
            'date': self.dismissal_date,
            'date_dismissal': self.dismissal_date,
            'dismissal_reason': self.dismissal_reason,
        })

    def _create_hiring_order(self, new_employee):
        return self.env['hr.order'].with_company(self.target_company_id).sudo().create({
            'order_type': 'hiring',
            'subject': 'Про прийняття на роботу (переведенням)',
            'employee_id': new_employee.id,
            'department_id': self.new_department_id.id,
            'job_id': self.new_job_id.id,
            'date': self.hire_date,
            'date_start': self.hire_date,
        })

    def _transfer_vacation_balance(self, new_employee):
        if self.vacation_transfer_mode != 'transfer':
            return
        Balance = self.env['hr.vacation.balance']
        if Balance._name not in self.env.registry:
            return
        year = self.hire_date.year
        source_balances = Balance.sudo().search([
            ('employee_id', '=', self.source_employee_id.id),
            ('year', '=', year),
        ])
        for bal in source_balances:
            remaining = (bal.total_available or 0) - (bal.used_days or 0)
            if remaining <= 0:
                continue
            Balance.sudo().create({
                'employee_id': new_employee.id,
                'leave_type_id': bal.leave_type_id.id,
                'year': year,
                'entitled_days': 0,
                'carried_over': remaining,
            })

    def action_transfer(self):
        self.ensure_one()
        if not self.hire_date:
            raise UserError(_('Вкажіть дату прийняття.'))
        source = self.source_employee_id
        if source.next_employee_id:
            raise UserError(_(
                'Цей співробітник вже переведений (див. "Наступний запис"). '
                'Повторне переведення з тієї ж картки не дозволено.'
            ))

        new_employee_vals = self._prepare_new_employee_vals()
        new_employee = self.env['hr.employee'].sudo().with_company(
            self.target_company_id,
        ).create(new_employee_vals)

        source.sudo().write({'next_employee_id': new_employee.id})

        self._copy_children(new_employee)
        self._copy_bank_accounts(new_employee)

        dismissal_order = self._create_dismissal_order()
        hiring_order = self._create_hiring_order(new_employee)

        self._transfer_vacation_balance(new_employee)

        source.sudo().write({'active': False})

        source.message_post(body=_(
            'Переведено в компанію <b>%(company)s</b>. Дата звільнення: %(date)s. '
            'Наказ про звільнення: %(order)s.',
            company=self.target_company_id.display_name,
            date=self.dismissal_date,
            order=dismissal_order.name or 'New',
        ))
        new_employee.message_post(body=_(
            'Прийнято переведенням з компанії <b>%(company)s</b>. Дата прийняття: %(date)s. '
            'Наказ про прийняття: %(order)s.',
            company=self.source_company_id.display_name,
            date=self.hire_date,
            order=hiring_order.name or 'New',
        ))

        return {
            'type': 'ir.actions.act_window',
            'name': new_employee.name,
            'res_model': 'hr.employee',
            'res_id': new_employee.id,
            'view_mode': 'form',
            'target': 'current',
        }
