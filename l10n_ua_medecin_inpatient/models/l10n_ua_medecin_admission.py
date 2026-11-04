from datetime import timezone
from zoneinfo import ZoneInfo

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


ADMISSION_STATE = [
    ('draft', 'Чернетка'),
    ('admitted', 'Госпіталізовано'),
    ('discharged', 'Виписано'),
    ('cancelled', 'Скасовано'),
]

ADMISSION_TYPE = [
    ('planned', 'Планова'),
    ('emergency', 'Екстрена'),
    ('transfer', 'Переведення з іншого закладу'),
    ('self_referral', 'Самозвернення'),
]

REFERRAL_SOURCE = [
    ('pmd', 'Лікар ПМД / амбулаторний заклад'),
    ('emd', 'Бригада екстреної (швидкої) допомоги'),
    ('self', 'Самозвернення'),
    ('other_facility', 'Інший заклад охорони здоров\'я'),
]

TREATMENT_RESULT = [
    ('recovery', 'Одужання'),
    ('improvement', 'Покращення'),
    ('no_change', 'Без змін'),
    ('deterioration', 'Погіршення'),
    ('death', 'Смерть'),
]

DISCHARGE_TYPE = [
    ('home', 'Виписаний додому'),
    ('transferred', 'Переведений в інший заклад'),
    ('left', 'Самовільно залишив стаціонар'),
    ('died', 'Помер'),
]

DEFAULT_TZ = 'Europe/Kyiv'


class L10nUaMedecinAdmission(models.Model):
    """Епізод стаціонарного лікування (пролікований випадок).

    Відповідає медичній карті стаціонарного хворого (ф. 003/о) і є джерелом
    даних для карти пацієнта, який вибув зі стаціонару (ф. 066/о), листка
    обліку руху хворих (ф. 007/о) та групування за ДСГ — форми затверджені
    наказом МОЗ України від 14.02.2012 № 110.
    """
    _name = 'l10n_ua.medecin.admission'
    _description = 'Епізод стаціонарного лікування'
    _order = 'date_admission desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(
        string='Номер карти (ф. 003/о)', required=True, copy=False,
        default='Нова', tracking=True, index=True,
        help='Номер медичної карти стаціонарного хворого; призначається '
             'автоматично при створенні.')
    state = fields.Selection(
        ADMISSION_STATE, string='Стан', default='draft', required=True,
        tracking=True, copy=False, index=True)
    company_id = fields.Many2one(
        'res.company', string='Заклад', required=True, index=True,
        default=lambda self: self.env.company, tracking=True)
    patient_id = fields.Many2one(
        'l10n_ua.medecin.patient', string='Пацієнт', required=True,
        ondelete='restrict', tracking=True, index=True, check_company=True)
    department_id = fields.Many2one(
        'l10n_ua.medecin.department', string='Відділення',
        ondelete='restrict', tracking=True, index=True, check_company=True)
    doctor_id = fields.Many2one(
        'hr.employee', string='Лікуючий лікар', ondelete='restrict',
        tracking=True, index=True, check_company=True)

    admission_type = fields.Selection(
        ADMISSION_TYPE, string='Вид госпіталізації', required=True,
        default='planned', tracking=True)
    referral_source = fields.Selection(
        REFERRAL_SOURCE, string='Ким направлений', tracking=True)
    referral_facility = fields.Char(
        string='Заклад, що направив / переводить',
        help='Назва закладу охорони здоров\'я, який направив пацієнта '
             'або з якого його переведено.')

    date_admission = fields.Datetime(
        string='Дата і час госпіталізації', required=True,
        default=fields.Datetime.now, tracking=True)
    date_discharge = fields.Datetime(
        string='Дата і час виписки', tracking=True, copy=False)
    bed_days = fields.Integer(
        string='Ліжко-дні', compute='_compute_bed_days', store=True,
        help='Кількість ліжко-днів: різниця календарних дат виписки і '
             'госпіталізації (день поступлення і день виписки разом — '
             'один ліжко-день); якщо пацієнт поступив і вибув того ж дня — '
             '1 ліжко-день. Дати беруться в часовому поясі закладу.')

    treatment_result = fields.Selection(
        TREATMENT_RESULT, string='Результат лікування', tracking=True,
        copy=False)
    discharge_type = fields.Selection(
        DISCHARGE_TYPE, string='Наслідок (вибуття)', tracking=True,
        copy=False)
    discharge_facility = fields.Char(
        string='Переведений до закладу', copy=False)

    notes = fields.Html(string='Примітки')

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'Номер карти стаціонарного хворого має бути унікальним у межах закладу.',
    )

    # === CRUD ===

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Нова') == 'Нова':
                company = self.env['res.company'].browse(
                    vals.get('company_id')) if vals.get('company_id') \
                    else self.env.company
                vals['name'] = self.env['ir.sequence'].with_company(
                    company).next_by_code('l10n_ua.medecin.admission') or 'Нова'
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft_or_cancelled(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(_(
                'Видалити можна лише чернетку або скасований епізод. '
                'Госпіталізацію/виписку спершу скасуйте.'))

    @api.depends('name', 'patient_id')
    def _compute_display_name(self):
        for rec in self:
            if rec.patient_id:
                rec.display_name = f"{rec.name} · {rec.patient_id.display_name}"
            else:
                rec.display_name = rec.name

    # === Ліжко-дні ===

    def _local_date(self, dt):
        """Календарна дата моменту `dt` (UTC, naive) у часовому поясі закладу."""
        self.ensure_one()
        tz_name = self.company_id.partner_id.tz or DEFAULT_TZ
        return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).date()

    @api.depends('date_admission', 'date_discharge', 'company_id')
    def _compute_bed_days(self):
        for rec in self:
            if not (rec.date_admission and rec.date_discharge) \
                    or rec.date_discharge < rec.date_admission:
                rec.bed_days = 0
                continue
            days = (rec._local_date(rec.date_discharge)
                    - rec._local_date(rec.date_admission)).days
            rec.bed_days = max(days, 1)

    # === Валідація ===

    @api.constrains('date_admission', 'date_discharge')
    def _check_dates(self):
        for rec in self:
            if rec.date_discharge and rec.date_discharge < rec.date_admission:
                raise ValidationError(_(
                    'Дата виписки (%(discharge)s) не може бути раніше дати '
                    'госпіталізації (%(admission)s).',
                    discharge=rec.date_discharge, admission=rec.date_admission))

    @api.constrains('state', 'date_discharge', 'treatment_result', 'discharge_type')
    def _check_discharge_data(self):
        for rec in self:
            if rec.state == 'discharged':
                if not rec.date_discharge:
                    raise ValidationError(_(
                        'Для виписаного епізоду має бути вказана дата виписки.'))
                if not rec.treatment_result or not rec.discharge_type:
                    raise ValidationError(_(
                        'Для виписки вкажіть результат лікування і наслідок.'))
            if rec.treatment_result and rec.discharge_type and (
                    (rec.treatment_result == 'death')
                    != (rec.discharge_type == 'died')):
                raise ValidationError(_(
                    'Результат лікування «Смерть» і наслідок «Помер» '
                    'зазначаються лише разом.'))

    # === Стейт-машина ===

    def action_admit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Госпіталізувати можна лише чернетку (%s).', rec.name))
        self.write({'state': 'admitted'})

    def action_discharge(self):
        for rec in self:
            if rec.state != 'admitted':
                raise UserError(_(
                    'Виписати можна лише госпіталізованого пацієнта (%s).', rec.name))
            vals = {'state': 'discharged'}
            if not rec.date_discharge:
                vals['date_discharge'] = max(fields.Datetime.now(), rec.date_admission)
            rec.write(vals)

    def action_reopen(self):
        """Повернути виписаний епізод у стан «Госпіталізовано» (виправлення)."""
        for rec in self:
            if rec.state != 'discharged':
                raise UserError(_('Повернути можна лише виписаний епізод (%s).', rec.name))
        self.write({'state': 'admitted'})

    def action_cancel(self):
        for rec in self:
            if rec.state not in ('draft', 'admitted'):
                raise UserError(_(
                    'Скасувати можна лише чернетку або госпіталізацію (%s). '
                    'Виписаний епізод спершу поверніть у стан «Госпіталізовано».',
                    rec.name))
        self.write({'state': 'cancelled'})

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('У чернетку можна повернути лише скасований епізод (%s).', rec.name))
        self.write({'state': 'draft'})
