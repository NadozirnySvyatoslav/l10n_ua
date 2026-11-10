from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class L10nUaMedecinAdmissionTransfer(models.Model):
    """Переведення пацієнта між відділеннями стаціонару в межах епізоду.

    Джерело граф «переведено з інших відділень» / «переведено в інші
    відділення» ф. 007/о. Після створення переведення поточне відділення
    (і ліжко, лікар) епізоду змінюються на нові.
    """
    _name = 'l10n_ua.medecin.admission.transfer'
    _description = 'Переведення між відділеннями'
    _order = 'date, id'
    _check_company_auto = True

    admission_id = fields.Many2one(
        'l10n_ua.medecin.admission', string='Епізод', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='admission_id.company_id', store=True, index=True, string='Заклад')
    date = fields.Datetime(
        string='Дата і час переведення', required=True, default=fields.Datetime.now)
    department_from_id = fields.Many2one(
        'l10n_ua.medecin.department', string='З відділення', required=True,
        ondelete='restrict', index=True, check_company=True)
    department_to_id = fields.Many2one(
        'l10n_ua.medecin.department', string='До відділення', required=True,
        ondelete='restrict', index=True, check_company=True)
    bed_id = fields.Many2one(
        'l10n_ua.medecin.bed', string='Ліжко', ondelete='restrict',
        check_company=True,
        domain="[('department_id', '=', department_to_id), ('is_occupied', '=', False)]")
    doctor_id = fields.Many2one(
        'hr.employee', string='Лікуючий лікар', ondelete='restrict',
        check_company=True,
        help='Новий лікуючий лікар; порожньо — без змін.')
    note = fields.Char(string='Причина / примітка')

    @api.depends('admission_id', 'department_to_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.department_from_id.name or ""} → {rec.department_to_id.name or ""}'

    @api.model_create_multi
    def create(self, vals_list):
        records = self.env['l10n_ua.medecin.admission.transfer']
        # По одному: кожне наступне переведення спирається на поточне відділення.
        for vals in vals_list:
            admission = self.env['l10n_ua.medecin.admission'].browse(vals.get('admission_id'))
            if admission.state != 'admitted':
                raise UserError(_(
                    'Перевести можна лише госпіталізованого пацієнта (%s).',
                    admission.display_name))
            vals.setdefault('department_from_id', admission.department_id.id)
            if vals['department_from_id'] != admission.department_id.id:
                raise UserError(_(
                    'Переводити можна лише з поточного відділення епізоду (%s).',
                    admission.department_id.display_name or '—'))
            date = fields.Datetime.to_datetime(vals.get('date')) or fields.Datetime.now()
            if admission.transfer_ids and date < max(admission.transfer_ids.mapped('date')):
                raise ValidationError(_(
                    'Нове переведення не може бути раніше попереднього (%s).',
                    admission.display_name))
            rec = super().create([vals])
            adm_vals = {'department_id': rec.department_to_id.id, 'bed_id': rec.bed_id.id}
            if rec.doctor_id:
                adm_vals['doctor_id'] = rec.doctor_id.id
            admission.write(adm_vals)
            records |= rec
        return records

    def write(self, vals):
        if {'admission_id', 'department_from_id', 'department_to_id'} & set(vals):
            raise UserError(_(
                'Відділення переведення змінити не можна: видаліть останнє '
                'переведення і створіть нове.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_last(self):
        for rec in self:
            adm = rec.admission_id
            if adm.state != 'admitted':
                raise UserError(_(
                    'Видалити переведення можна лише для госпіталізованого '
                    'пацієнта (%s).', adm.display_name))
            if rec != adm.transfer_ids.sorted(lambda t: (t.date, t.id))[-1:]:
                raise UserError(_('Видаляти можна лише останнє переведення.'))

    def unlink(self):
        restore = [(rec.admission_id, rec.department_from_id) for rec in self]
        res = super().unlink()
        for admission, department in restore:
            if admission.exists():
                admission.write({'department_id': department.id, 'bed_id': False})
        return res

    @api.constrains('date', 'department_from_id', 'department_to_id')
    def _check_transfer(self):
        for rec in self:
            adm = rec.admission_id
            if rec.department_from_id == rec.department_to_id:
                raise ValidationError(_('Відділення «з» і «до» мають відрізнятися.'))
            if rec.date < adm.date_admission:
                raise ValidationError(_(
                    'Переведення не може бути раніше госпіталізації (%s).', adm.display_name))
            if adm.date_discharge and adm.state == 'discharged' and rec.date > adm.date_discharge:
                raise ValidationError(_(
                    'Переведення не може бути пізніше виписки (%s).', adm.display_name))
            adm._check_transfer_chain()
