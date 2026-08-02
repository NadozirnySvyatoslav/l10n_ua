from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# Fields copied verbatim into the target employee's create() values. Only
# scalars and Many2one belong here: _prepare_new_employee_vals reads `value.id`,
# which raises on a multi-record set. `bank_account_ids` in particular must
# never be listed — it would both break on that read and carry over accounts
# owned by the source partner and source company. Bank accounts are handled by
# _copy_bank_accounts, which re-creates them under the target contact.
PERSONAL_FIELDS = [
    # Standard Odoo personal data
    'name', 'gender', 'birthday', 'place_of_birth', 'country_of_birth',
    'country_id', 'identification_id', 'lang',
    'marital', 'spouse_complete_name', 'spouse_birthdate',
    'private_phone', 'private_email', 'private_street',
    'private_street2', 'private_city', 'private_zip', 'private_state_id',
    'private_country_id',
    # Work contact info shown directly under the name in the form header
    'job_title', 'work_phone', 'mobile_phone', 'work_email',
    # Ukrainian-specific personal data from l10n_ua_hr_base
    'rnokpp', 'document_type', 'passport_series',
    'passport_id', 'passport_expiration_date',
    'passport_issued_by', 'passport_issued_date', 'passport_record_number',
    'registration_street', 'registration_street2', 'registration_region_id', 'registration_city',
    'registration_zip', 'registration_same_as_actual',
    'education_level_id', 'study_school', 'study_field',
    'diploma_series', 'diploma_number', 'diploma_date',
    'military_status', 'military_register_category', 'military_category',
    'military_rank_id', 'military_specialty', 'military_fitness',
    'military_medical_category', 'military_mlk_retest_date',
    'military_document_number',
    'military_tcc_id', 'military_reservation', 'military_reservation_until',
    'military_reservplus_id',
    'disability_group', 'disability_reason', 'disability_document',
    'disability_date_from', 'disability_date_to',
    'chornobyl_category', 'veteran_status', 'spouse_rnokpp',
    # Work experience (company experience recomputes from new hire_date)
    'work_experience_total', 'insurance_experience',
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

    copy_wage = fields.Boolean(
        string='Перенести умови оплати з джерела', default=True,
        help='Скопіювати оклад та умови (тип договору, режим, ставку) з '
             'поточної версії контракту працівника. За згодою сторін.')
    new_wage = fields.Monetary(
        string='Оклад (target)', compute='_compute_new_wage',
        store=True, readonly=False, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='target_company_id.currency_id')

    copy_bank_accounts = fields.Boolean(string='Copy Bank Accounts', default=True)
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
    vacation_period_mode = fields.Selection(
        [
            ('keep', 'Keep Work Year (preserve hire_date)'),
            ('reset', 'New Work Year (from transfer date)'),
        ],
        string='Vacation Work Year', default='keep',
        help='For annual (work-year) leaves. "keep": preserve the original '
             'hire date so the work year continues (same period). "reset": '
             'start a new work year from the transfer date. Calendar leave '
             'types are unaffected by this mode.',
    )

    @api.depends('dismissal_date')
    def _compute_hire_date(self):
        for wiz in self:
            wiz.hire_date = (wiz.dismissal_date + timedelta(days=1)) if wiz.dismissal_date else False

    @api.depends('source_employee_id', 'copy_wage')
    def _compute_new_wage(self):
        for wiz in self:
            src_version = wiz.source_employee_id.current_version_id
            wiz.new_wage = (src_version.wage or 0.0) if (
                wiz.copy_wage and src_version) else 0.0

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
        """Values for the employee record created in the target company.

        hire_date is deliberately absent: it is computed from the contract
        versions, and `_create_new_version` sets contract_date_start on the
        new employee's version in the same transaction, right after the
        record is created. Writing it here as well would make the wizard a
        second source for a date the version already owns.

        The work year carried over in "keep" mode therefore travels in
        `vacation_anchor_date` instead: the new contract legitimately starts
        on the transfer date, only the vacation seniority keeps running.
        """
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
        # "keep": the annual (work-year) vacation seniority continues, so the
        # anchor of the source travels along — its own anchor when it was
        # itself transferred, its hire date otherwise. "reset": no anchor, the
        # work year starts from the new hire date (= the transfer date).
        # The field lives in l10n_ua_hr_holidays, which this module does not
        # depend on.
        if 'vacation_anchor_date' in source._fields:
            vals['vacation_anchor_date'] = (
                source._get_vacation_anchor_date()
                if self.vacation_period_mode == 'keep' else False)
        if not self.copy_documents:
            for fname in ('passport_series', 'passport_id', 'passport_expiration_date',
                          'passport_issued_by', 'passport_issued_date',
                          'passport_record_number',
                          'diploma_series', 'diploma_number', 'diploma_date',
                          'education_level_id', 'study_school', 'study_field'):
                vals.pop(fname, None)
        if not self.copy_family_data:
            for fname in ('spouse_rnokpp', 'spouse_complete_name',
                          'spouse_birthdate', 'marital'):
                vals.pop(fname, None)
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
        """Re-create the source accounts under the target contact and link them.

        Every account of the source work contact is copied, as before, but only
        those the source employee used for payroll are linked to the new
        `bank_account_ids`: the rest are private accounts that never took part
        in a salary payment.

        The copies satisfy the native domain by construction — their partner is
        the target work contact and their company is the target company — which
        is exactly why the link cannot be made through PERSONAL_FIELDS instead.
        `allow_out_payment` has copy=False, so a copied account arrives
        untrusted and an officer has to authorise outgoing payments explicitly.
        """
        if not self.copy_bank_accounts or not self.source_employee_id.work_contact_id:
            return
        source = self.source_employee_id
        target_partner = new_employee.work_contact_id
        if not target_partner:
            return
        Bank = self.env['res.partner.bank'].sudo()
        copied_by_source = {}
        for bank in source.work_contact_id.bank_ids:
            copy_vals = bank.copy_data()[0]
            copy_vals['partner_id'] = target_partner.id
            copy_vals['company_id'] = self.target_company_id.id
            copied_by_source[bank.id] = Bank.create(copy_vals)
        salary_accounts = [
            copied_by_source[bank.id].id
            for bank in source.bank_account_ids
            if bank.id in copied_by_source
        ]
        if salary_accounts:
            new_employee.sudo().bank_account_ids = [(6, 0, salary_accounts)]

    def _create_new_version(self, new_employee):
        """Налаштувати версію трудового договору для прийнятого працівника.

        Нова картка `hr.employee` вже має авто-створену версію — оновлюємо ЇЇ
        (дата = дата прийняття, оплата й умови), щоб не плодити дублікатів і
        щоб вона стала поточною. Дата версії = дата прийняття, тож наказ
        прийняття (його sync) знайде саме її за ``date_version``. Умови оплати
        переносяться з джерела за згодою сторін.
        """
        self.ensure_one()
        Version = self.env['hr.version']
        src = self.source_employee_id.current_version_id
        vals = {
            'company_id': self.target_company_id.id,
            'contract_date_start': self.hire_date,
            'date_version': self.hire_date,
            'wage': self.new_wage or 0.0,
        }
        if self.new_job_id and 'job_id' in Version._fields:
            vals['job_id'] = self.new_job_id.id
        if self.new_department_id and 'department_id' in Version._fields:
            vals['department_id'] = self.new_department_id.id
        # Перенести умови (тип договору, режим, ставку) з джерела за згодою.
        if self.copy_wage and src:
            for fname in ('contract_type_ua', 'work_mode', 'work_rate'):
                if fname in src._fields and fname in Version._fields and src[fname]:
                    vals[fname] = src[fname]

        version = new_employee.current_version_id or new_employee.with_context(
            active_test=False).version_ids[:1]
        if version:
            version.sudo().write(vals)
        else:
            vals['employee_id'] = new_employee.id
            version = Version.sudo().create(vals)
        new_employee.sudo().write({'current_version_id': version.id})
        return version

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
            'personnel_form': 'p4',
        })

    def _create_hiring_order(self, new_employee, new_version):
        return self.env['hr.order'].with_company(self.target_company_id).sudo().create({
            'order_type': 'hiring',
            'subject': 'Про прийняття на роботу (переведенням)',
            'employee_id': new_employee.id,
            'department_id': self.new_department_id.id,
            'job_id': self.new_job_id.id,
            'date': self.hire_date,
            'date_start': self.hire_date,
            'personnel_form': 'p7',
            'new_version_id': new_version.id,
        })

    def _transfer_vacation_balance(self, new_employee):
        if self.vacation_transfer_mode != 'transfer':
            return
        if 'hr.vacation.balance' not in self.env:
            return
        Balance = self.env['hr.vacation.balance']
        transfer_date = self.hire_date
        # Source periods that are CURRENT as of the transfer date (the period
        # contains it) — one active period per leave type. Replaces the old
        # year-based lookup so work-year and calendar periods both resolve.
        source_balances = Balance.sudo().search([
            ('employee_id', '=', self.source_employee_id.id),
            ('period_start', '<=', transfer_date),
            ('period_end', '>=', transfer_date),
        ])
        for bal in source_balances:
            remaining = (bal.total_available or 0) - (bal.used_days or 0)
            if remaining <= 0:
                continue
            leave_type = bal.leave_type_id
            if (leave_type.period_type == 'work'
                    and self.vacation_period_mode == 'reset'):
                # New work year counted from the transfer date (the new
                # employee's hire_date is the transfer date in this mode).
                start, end, index = new_employee._get_work_year_for_date(
                    transfer_date)
            else:
                # "keep" (work year continues) or a calendar type: carry the
                # remaining days into the same period bounds as the source.
                start, end, index = (
                    bal.period_start, bal.period_end, bal.period_index)
            if not start:
                continue
            Balance.sudo().create({
                'employee_id': new_employee.id,
                'leave_type_id': leave_type.id,
                'company_id': new_employee.company_id.id,
                'period_start': start,
                'period_end': end,
                'period_index': index,
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

        new_version = self._create_new_version(new_employee)

        dismissal_order = self._create_dismissal_order()
        hiring_order = self._create_hiring_order(new_employee, new_version)

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
