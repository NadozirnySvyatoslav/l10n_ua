from odoo import models, fields, api, _


class ResCompany(models.Model):
    _inherit = 'res.company'

    ua_leave_types_imported = fields.Boolean(
        string='UA Leave Types Imported',
        default=False,
        help='Indicates if Ukrainian leave types have been imported for this company'
    )

    def action_import_ua_leave_types(self):
        """Import Ukrainian leave types for the company"""
        self.ensure_one()
        
        leave_type_data = [
            {
                'name': 'Щорічна основна відпустка',
                'ua_leave_category': 'annual_basic',
                'annual_days': 24,
                'is_calendar_days': True,
                'is_transferable': True,
                'ua_auto_calc_balance': True,
                'requires_experience': True,
                'min_experience_months': 6,
                'is_paid': True,
                'payment_source': 'employer',
                'min_continuous_days': 14,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Щорічна додаткова відпустка',
                'ua_leave_category': 'annual_additional',
                'annual_days': 7,
                'is_calendar_days': True,
                'is_transferable': True,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Навчальна відпустка',
                'ua_leave_category': 'educational',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Творча відпустка',
                'ua_leave_category': 'creative',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Соціальна відпустка (на дітей)',
                'ua_leave_category': 'social_children',
                'annual_days': 10,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка без збереження зарплати',
                'ua_leave_category': 'unpaid',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': False,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка без збереження зарплати (сімейні обставини)',
                'ua_leave_category': 'unpaid',
                'annual_days': 15,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': False,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка без збереження зарплати (виїзд за кордон або ВПО)',
                'ua_leave_category': 'unpaid_abroad',
                'annual_days': 90,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': False,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка без збереження зарплати (догляд за дитиною до 6 років)',
                'ua_leave_category': 'unpaid_childcare',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': False,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка у зв\'язку з вагітністю та пологами',
                'ua_leave_category': 'maternity',
                'annual_days': 126,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'fss',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Відпустка для догляду за дитиною до 3 років',
                'ua_leave_category': 'childcare',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': False,
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Лікарняний',
                'ua_leave_category': 'sick',
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'mixed',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Додаткова за шкідливі умови праці',
                'ua_leave_category': 'annual_hazardous',
                'annual_days': 35,
                'is_calendar_days': True,
                'is_transferable': True,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Додаткова за ненормований робочий день',
                'ua_leave_category': 'annual_irregular',
                'annual_days': 7,
                'is_calendar_days': True,
                'is_transferable': True,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Додаткова за особливий характер праці',
                'ua_leave_category': 'annual_special',
                'annual_days': 35,
                'is_calendar_days': True,
                'is_transferable': True,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Додаткова чорнобильцям',
                'ua_leave_category': 'chornobyl',
                'annual_days': 16,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
            {
                'name': 'Додаткова ветеранам війни',
                'ua_leave_category': 'veteran',
                'annual_days': 14,
                'is_calendar_days': True,
                'is_transferable': False,
                'is_paid': True,
                'payment_source': 'employer',
                'request_unit': 'day',
                'leave_validation_type': 'hr',
            },
        ]

        LeaveType = self.env['hr.leave.type'].sudo()
        created_count = 0
        
        for data in leave_type_data:
            existing = LeaveType.search([
                ('name', '=', data['name']),
                ('company_id', '=', self.id),
            ], limit=1)
            
            if not existing:
                data['company_id'] = self.id
                # UA leave entitlement is tracked via hr.vacation.balance,
                # not core allocations — don't demand an allocation record.
                data.setdefault('requires_allocation', False)
                LeaveType.create(data)
                created_count += 1

        self.sudo().ua_leave_types_imported = True
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('UA Leave Types Imported'),
                # Named placeholders so translators may reorder them freely;
                # positional %d/%s would swap the values and raise on reorder.
                'message': _(
                    '%(count)d leave types have been created for %(company)s',
                    count=created_count, company=self.name),
                'type': 'success',
                'sticky': False,
            }
        }
