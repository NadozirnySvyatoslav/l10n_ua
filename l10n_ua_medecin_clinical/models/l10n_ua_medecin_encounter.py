from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


ENCOUNTER_TYPE = [
    ('consultation', 'Консультація'),
    ('check_up', 'Профілактичний огляд'),
    ('home_visit', 'Виклик додому'),
    ('emergency', 'Невідкладна допомога'),
    ('procedure', 'Маніпуляція / процедура'),
    ('diagnostics', 'Діагностичне дослідження'),
]

ENCOUNTER_STATE = [
    ('planned', 'Заплановано'),
    ('in_progress', 'У процесі'),
    ('finished', 'Завершено'),
    ('cancelled', 'Скасовано'),
]


class L10nUaMedecinEncounter(models.Model):
    """Медичний прийом / контакт з пацієнтом."""
    _name = 'l10n_ua.medecin.encounter'
    _description = 'Медичний прийом'
    _order = 'date_start desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Номер', compute='_compute_name', store=True)
    patient_id = fields.Many2one('l10n_ua.medecin.patient', string='Пацієнт', required=True,
                                   ondelete='restrict', tracking=True, index=True)
    doctor_id = fields.Many2one('hr.employee', string='Лікар', required=True,
                                  ondelete='restrict', tracking=True, index=True)
    company_id = fields.Many2one('res.company', required=True,
                                   default=lambda self: self.env.company)
    encounter_type = fields.Selection(ENCOUNTER_TYPE, string='Тип прийому', default='consultation',
                                        required=True, tracking=True)
    state = fields.Selection(ENCOUNTER_STATE, string='Стан', default='planned', required=True,
                               tracking=True, copy=False)
    date_start = fields.Datetime(string='Початок', required=True,
                                   default=fields.Datetime.now, tracking=True)
    date_end = fields.Datetime(string='Завершення', tracking=True)
    complaint = fields.Text(string='Скарги / Анамнез')
    examination = fields.Text(string='Об\'єктивний огляд')
    diagnosis_ids = fields.One2many('l10n_ua.medecin.diagnosis', 'encounter_id',
                                      string='Діагнози')
    treatment = fields.Html(string='Призначене лікування')
    notes = fields.Html(string='Додатково')

    @api.depends('patient_id', 'date_start')
    def _compute_name(self):
        for rec in self:
            if rec.patient_id and rec.date_start:
                rec.name = f"{rec.patient_id.display_name} · {rec.date_start}"
            else:
                rec.name = _('Новий прийом')

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_finish(self):
        self.write({
            'state': 'finished',
            'date_end': fields.Datetime.now(),
        })

    def action_cancel(self):
        self.write({'state': 'cancelled'})


DIAGNOSIS_TYPE = [
    ('referral', 'Діагноз закладу, що направив'),
    ('admission', 'При госпіталізації (попередній)'),
    ('clinical', 'Клінічний'),
    ('final', 'Заключний (основний)'),
    ('pathological', 'Патолого-анатомічний'),
    ('concomitant', 'Супутній'),
    ('complication', 'Ускладнення'),
]


class L10nUaMedecinDiagnosis(models.Model):
    """Діагноз пацієнта за МКХ-10.

    Належить амбулаторному прийому (`encounter_id`) або — у модулі
    l10n_ua_medecin_inpatient — епізоду стаціонарного лікування
    (`admission_id`); рівно одному з них (#225). Тип діагнозу розрізняє
    діагноз направлення, при госпіталізації, клінічний, заключний,
    патолого-анатомічний, а також супутні захворювання й ускладнення
    (ф. 066/о, наказ МОЗ № 110).
    """
    _name = 'l10n_ua.medecin.diagnosis'
    _description = 'Діагноз пацієнта'
    _order = 'encounter_id, sequence, id'

    encounter_id = fields.Many2one('l10n_ua.medecin.encounter', string='Прийом',
                                     ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    icd10_id = fields.Many2one('l10n_ua.medecin.icd10', string='МКХ-10', required=True,
                                 ondelete='restrict',
                                 domain=[('is_selectable', '=', True)])
    icd10_code = fields.Char(related='icd10_id.code', store=True, readonly=True)
    diagnosis_type = fields.Selection(
        DIAGNOSIS_TYPE, string='Тип діагнозу', required=True, default='clinical',
        index=True)
    is_first_detected = fields.Boolean(
        string='Виявлено вперше',
        help='Захворювання виявлене вперше в житті пацієнта.')
    date_established = fields.Date(
        string='Дата встановлення', default=fields.Date.context_today)
    # Збережені поля «контексту» — для групування/звітності «Захворюваність»
    # (пацієнт / лікар / місяць) без JOIN через прийом у кожному запиті.
    # Беруться з власника діагнозу; l10n_ua_medecin_inpatient розширює
    # _compute_owner_fields епізодом стаціонарного лікування.
    patient_id = fields.Many2one('l10n_ua.medecin.patient', string='Пацієнт',
                                 compute='_compute_owner_fields', store=True,
                                 index=True)
    doctor_id = fields.Many2one('hr.employee', string='Лікар',
                                compute='_compute_owner_fields', store=True,
                                index=True)
    date_start = fields.Datetime(string='Дата прийому / госпіталізації',
                                 compute='_compute_owner_fields', store=True)
    company_id = fields.Many2one('res.company', compute='_compute_owner_fields',
                                 store=True, index=True)
    # Зворотна сумісність: «Основний» == заключний діагноз. Позначка галочки
    # робить діагноз заключним, зняття — повертає тип «Клінічний».
    is_primary = fields.Boolean(string='Основний', compute='_compute_is_primary',
                                inverse='_inverse_is_primary', store=True,
                                readonly=False)
    is_chronic = fields.Boolean(string='Хронічний')
    note = fields.Char(string='Примітка')

    @api.depends('encounter_id.patient_id', 'encounter_id.doctor_id',
                 'encounter_id.date_start', 'encounter_id.company_id')
    def _compute_owner_fields(self):
        for rec in self:
            enc = rec.encounter_id
            rec.patient_id = enc.patient_id
            rec.doctor_id = enc.doctor_id
            rec.date_start = enc.date_start
            rec.company_id = enc.company_id

    @api.depends('diagnosis_type')
    def _compute_is_primary(self):
        for rec in self:
            rec.is_primary = rec.diagnosis_type == 'final'

    def _inverse_is_primary(self):
        for rec in self:
            if rec.is_primary and rec.diagnosis_type != 'final':
                rec.diagnosis_type = 'final'
            elif not rec.is_primary and rec.diagnosis_type == 'final':
                rec.diagnosis_type = 'clinical'

    @api.model
    def _owner_field_names(self):
        """Поля-власники діагнозу; заповнене має бути рівно одне."""
        return ['encounter_id']

    # icd10_id обов'язковий і завжди є у vals при створенні — так перевірка
    # спрацьовує й тоді, коли жодного власника не передано.
    @api.constrains('encounter_id', 'icd10_id')
    def _check_single_owner(self):
        names = self._owner_field_names()
        labels = ', '.join(self._fields[n].string for n in names)
        for rec in self:
            if sum(1 for n in names if rec[n]) != 1:
                raise ValidationError(_(
                    'Діагноз має належати рівно одному документу: %s.', labels))
