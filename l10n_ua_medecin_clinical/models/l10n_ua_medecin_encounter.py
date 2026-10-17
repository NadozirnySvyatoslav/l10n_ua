from odoo import api, fields, models, _


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


class L10nUaMedecinDiagnosis(models.Model):
    _name = 'l10n_ua.medecin.diagnosis'
    _description = 'Діагноз пацієнта'
    _order = 'encounter_id, sequence'

    encounter_id = fields.Many2one('l10n_ua.medecin.encounter', required=True,
                                     ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    icd10_id = fields.Many2one('l10n_ua.medecin.icd10', string='МКХ-10', required=True,
                                 ondelete='restrict',
                                 domain=[('is_selectable', '=', True)])
    icd10_code = fields.Char(related='icd10_id.code', store=True, readonly=True)
    # Збережені related-поля — для групування/звітності «Захворюваність»
    # (пацієнт / лікар / місяць) без JOIN через прийом у кожному запиті.
    patient_id = fields.Many2one(related='encounter_id.patient_id', store=True,
                                 index=True, string='Пацієнт')
    doctor_id = fields.Many2one(related='encounter_id.doctor_id', store=True,
                                index=True, string='Лікар')
    date_start = fields.Datetime(related='encounter_id.date_start', store=True,
                                 string='Дата прийому')
    company_id = fields.Many2one(related='encounter_id.company_id', store=True,
                                 index=True)
    is_primary = fields.Boolean(string='Основний', default=False)
    is_chronic = fields.Boolean(string='Хронічний')
    note = fields.Char(string='Примітка')
